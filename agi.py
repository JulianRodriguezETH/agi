"""AGI: conteo de ganado con dron. Aplicacion de escritorio.

  python agi.py

Dos destinos: Fincas y Ajustes. Todo empieza en una finca. Contar tiene tres
pasos: Fotos, Revisar, Reporte. Al terminar, AGI avisa los hallazgos.

Necesita: PySide6-Essentials, onnxruntime, opencv-python, numpy, cryptography, sqlcipher3-wheels.
"""
import datetime
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

import contar
import datos
import excel
import reporte
import seguridad
import vuelo
from piezas import (ACENTO, ARCHIVO_REVISION, AZUL, BORDE, CLARO, CONF_DEFECTO, FONDO, FONDO_ROJO,
                    GRIS, LINEA, MODELO, RELIEVE, ROJO, SELECCION, SUPERFICIE, TEXTO, TINTA, VERDE,
                    Detector, DialogoAcceso, DialogoRespaldo, DialogoUsuarios, Extractor, Foto, Marca, Panel, Visor,
                    brillo, cargar_fuentes, carpeta_datos, comprobar_modelo, crear_sesion, guardar_imagen, icono,
                    insignia, instalar_registro_errores, leer_imagen, pixmap_marca, sombra, tomar_candado)

CAIDA_ALERTA = 5.0
MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TITULOS = '"Manrope", "Segoe UI", "Inter", sans-serif'      # Manrope va en la carpeta fuentes/

# Tema oscuro: pagina negra, tarjetas gris carbon con borde fino, botones en pildora; blanco como acento y azul pizarra en lo destacado.
# Ojo con las pildoras: Qt dibuja la esquina cuadrada si el radio no es menor que la mitad del alto; por eso cada
# boton fija su alto minimo y usa un radio un poco menor.
ESTILO = f"""
QWidget {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 14px; color: {TEXTO}; }}
QMainWindow, QDialog, #pagina {{ background: {FONDO}; }}
#barra {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17181B, stop:1 #0E0E10); }}
#barra QLabel {{ color: {TEXTO}; background: transparent; font-weight: 500; }}
#barra QPushButton#nav {{ border: none; padding: 10px 16px; min-height: 18px; border-radius: 17px; font-size: 15px; font-weight: 500; background: transparent; color: {GRIS}; }}
#barra QPushButton#nav:hover {{ color: {TEXTO}; background: transparent; }}
#barra QPushButton#nav:checked {{ background: rgba(255, 255, 255, 0.10); color: {ACENTO}; font-weight: 600; }}
#barra QPushButton#respaldo {{ border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 15px; padding: 6px 14px; min-height: 18px; font-size: 13px; font-weight: 500; background: rgba(255, 255, 255, 0.06); color: {CLARO}; }}
#barra QPushButton#respaldo:hover {{ border-color: #666666; color: {TEXTO}; }}
#barra QLabel#avatar {{ background: #2A2A2A; color: {ACENTO}; border-radius: 16px; font-weight: 600; }}
#titulo {{ font-family: {TITULOS}; font-size: 32px; font-weight: 700; }}
#seccion {{ font-size: 16px; font-weight: 600; }}
#h2 {{ font-family: "Manrope SemiBold", {TITULOS}; font-size: 28px; font-weight: 600; }}
#h3 {{ font-family: "Manrope SemiBold", {TITULOS}; font-size: 20px; font-weight: 600; }}
#h2_sub {{ color: {GRIS}; font-size: 15px; }}
#destacado {{ font-family: {TITULOS}; font-size: 20px; font-weight: 700; }}
#sub {{ color: {GRIS}; font-size: 15px; }}
#gris {{ color: {GRIS}; }}
#rotulo {{ color: {GRIS}; font-size: 11px; font-weight: 600; }}
#numero {{ font-family: {TITULOS}; font-size: 64px; font-weight: 700; }}
#numero_med {{ font-family: {TITULOS}; font-size: 28px; font-weight: 700; }}
#heroe QLabel {{ background: transparent; color: {CLARO}; }}
#heroe QLabel#heroe_rotulo {{ font-size: 11px; font-weight: 600; letter-spacing: 1.4px; }}
#heroe QLabel#heroe_numero {{ color: {ACENTO}; font-family: {TITULOS}; font-size: 60px; font-weight: 700; }}
#heroe QLabel#heroe_valor {{ color: {TEXTO}; font-family: {TITULOS}; font-size: 24px; font-weight: 700; }}
#premio QLabel {{ background: transparent; color: {CLARO}; font-size: 15px; }}
#premio QLabel#heroe_rotulo {{ font-size: 12px; font-weight: 600; letter-spacing: 1.6px; }}
#premio QLabel#heroe_numero {{ color: {ACENTO}; font-family: {TITULOS}; font-size: 84px; font-weight: 700; }}
#separador {{ background: rgba(255, 255, 255, 0.10); max-width: 1px; min-width: 1px; }}
#beneficios QLabel {{ background: transparent; }}
#anuncio QLabel {{ background: transparent; color: {CLARO}; font-size: 15px; }}
#anuncio QLabel#h3 {{ color: {TEXTO}; font-size: 18px; }}
#caja QLabel {{ background: transparent; }}
#aviso QLabel {{ color: {TEXTO}; background: transparent; }}
#aviso QPushButton {{ color: {AZUL}; font-weight: 600; border: none; background: transparent; text-decoration: underline; padding: 8px; }}
#paso {{ font-size: 15px; color: {GRIS}; }}
#paso[estado="actual"] {{ color: {TEXTO}; font-weight: 600; }}
#paso_n {{ border-radius: 13px; font-size: 13px; font-weight: 600; border: 1px solid #5A5A5A; color: {GRIS}; background: transparent; }}
#paso_n[estado="actual"] {{ background: {ACENTO}; border-color: {ACENTO}; color: {TINTA}; }}
#paso_n[estado="hecho"] {{ background: rgba(157, 189, 242, 0.16); border-color: rgba(157, 189, 242, 0.45); color: {ACENTO}; }}
QPushButton {{ background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 19px; min-height: 19px; padding: 10px 16px; font-weight: 600; color: {TEXTO}; }}
QPushButton:hover {{ border-color: rgba(255, 255, 255, 0.34); background: rgba(255, 255, 255, 0.13); }}
QPushButton:pressed {{ background: rgba(255, 255, 255, 0.05); }}
QPushButton:disabled {{ color: #666666; border-color: rgba(255, 255, 255, 0.07); background: rgba(255, 255, 255, 0.03); }}
QPushButton#primario {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FFFFFF, stop:1 #D9E0EC); color: {TINTA}; border: 1px solid {ACENTO}; border-radius: 21px; min-height: 20px; padding: 12px 24px; font-weight: 600; font-size: 15px; }}
QPushButton#primario:hover {{ background: #FFFFFF; border-color: #FFFFFF; }}
QPushButton#primario:pressed {{ background: #CCCCCC; border-color: #CCCCCC; }}
QPushButton#primario:disabled {{ background: rgba(255, 255, 255, 0.07); border-color: rgba(255, 255, 255, 0.05); color: #666666; }}
QPushButton#secundario {{ background: rgba(255, 255, 255, 0.08); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 21px; min-height: 20px; padding: 12px 20px; font-weight: 600; font-size: 15px; }}
QPushButton#secundario:hover {{ border-color: rgba(255, 255, 255, 0.34); background: rgba(255, 255, 255, 0.13); }}
QPushButton#secundario:checked {{ background: rgba(157, 189, 242, 0.22); color: {TEXTO}; border-color: {AZUL}; }}
QPushButton#plano {{ border: none; background: transparent; color: {GRIS}; padding: 10px 12px; font-weight: 500; }}
QPushButton#plano:hover {{ color: {TEXTO}; background: transparent; }}
QLineEdit, QComboBox, QDateEdit, QSpinBox {{ min-height: 42px; border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; padding: 0 12px; background: rgba(0, 0, 0, 0.35); color: {TEXTO};
    selection-background-color: #34486A; selection-color: {TEXTO}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus {{ border: 1px solid {AZUL}; background: rgba(107, 155, 225, 0.10); }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled {{ color: #808080; border-color: rgba(255, 255, 255, 0.07); }}
QLineEdit:read-only {{ color: {GRIS}; }}
QTableWidget {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1A1A1C, stop:1 #101011); border: 1px solid #2A2A2D; border-radius: 16px; padding: 6px; gridline-color: {RELIEVE}; }}
QTableWidget::item {{ padding: 0 18px; border-bottom: 1px solid {RELIEVE}; }}
QTableWidget::item:selected {{ background: {SELECCION}; color: {TEXTO}; }}
QSpinBox QLineEdit, QDateEdit QLineEdit, QComboBox QLineEdit {{ border: none; min-height: 0; padding: 0; background: transparent; }}
QPlainTextEdit, QTextEdit, QListWidget {{ background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 12px; padding: 8px; color: {TEXTO}; }}
QListWidget::item:selected {{ background: {SELECCION}; color: {TEXTO}; }}
QCheckBox {{ spacing: 10px; }}
QSlider::groove:horizontal {{ height: 6px; background: {BORDE}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {CLARO}; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {ACENTO}; border: 2px solid {FONDO}; width: 14px; margin: -6px 0; border-radius: 9px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
QScrollBar::handle {{ background: #3D3D3D; border-radius: 4px; min-height: 32px; min-width: 32px; }}
QScrollBar::handle:hover {{ background: #5A5A5A; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 26px; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; border: none; border-bottom: 1px solid {LINEA}; padding: 14px 18px 10px 18px; color: {GRIS}; font-size: 11px; font-weight: 600; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 10px 4px; margin-right: 22px; color: {GRIS}; font-size: 15px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXTO}; font-weight: 600; border-bottom: 2px solid {TEXTO}; }}
QStatusBar {{ background: {FONDO}; border-top: 1px solid {LINEA}; color: {GRIS}; font-size: 12px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {GRIS}; font-size: 12px; }}
#panel_marca QLabel {{ color: {CLARO}; background: transparent; font-size: 14px; }}
#panel_marca QLabel#lema {{ font-family: "Manrope SemiBold", "Segoe UI", sans-serif; font-size: 30px; color: {TEXTO}; }}
#panel_marca QLabel#lema_sub {{ font-size: 15px; }}
#entrar_titulo {{ font-family: {TITULOS}; font-size: 28px; font-weight: 700; }}
#campo {{ font-size: 13px; font-weight: 600; }}
#error {{ color: {ROJO}; }}
#panel_marca QLabel#error_oscuro {{ color: #FFB59E; }}
#panel_marca QLineEdit {{ color: {TEXTO}; padding: 0 12px; }}
QTableWidget::item:hover {{ background: #1A1A1A; }}
QProgressBar {{ background: {BORDE}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; color: transparent; }}
QProgressBar::chunk {{ background: {ACENTO}; border-radius: 3px; }}
QToolTip {{ background: #262626; color: {TEXTO}; border: 1px solid {BORDE}; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
QMenu {{ background: #1A1A1A; border: 1px solid {BORDE}; border-radius: 10px; padding: 6px; color: {TEXTO}; }}
QMenu::item {{ padding: 8px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: #2E2E2E; color: {TEXTO}; }}
QComboBox QAbstractItemView {{ background: #1A1A1A; color: {TEXTO}; border: 1px solid {BORDE}; border-radius: 10px; padding: 4px; outline: none;
    selection-background-color: #2E2E2E; selection-color: {TEXTO}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {SUPERFICIE}; }}
QCalendarWidget QToolButton {{ color: {TEXTO}; background: transparent; font-weight: 600; padding: 6px; }}
QCalendarWidget QAbstractItemView {{ background: {SUPERFICIE}; color: {TEXTO}; alternate-background-color: #1A1A1A;
    selection-background-color: {ACENTO}; selection-color: {TINTA}; outline: none; }}
QCalendarWidget QAbstractItemView:disabled {{ color: #555555; }}
QPushButton#enlace {{ color: {AZUL}; font-weight: 600; border: none; background: transparent; text-decoration: underline; padding: 8px; }}
#resumen_rev {{ color: {GRIS}; }}
QPushButton#pestana {{ border: none; background: transparent; color: {GRIS}; padding: 6px 12px; min-height: 16px; border-radius: 13px; font-size: 13px; font-weight: 600; }}
QPushButton#pestana:checked {{ background: rgba(255, 255, 255, 0.12); color: {TEXTO}; }}
QPushButton#pestana:hover {{ color: {TEXTO}; }}
#caja_oscura QLabel {{ background: transparent; color: {CLARO}; }}
#caja_oscura QLabel#numero_med {{ color: {ACENTO}; }}
"""


def paleta_oscura():
    """Colores base para lo que la hoja de estilos no pinta (casillas, calendario, ventanas de archivo)."""
    R, C = QtGui.QPalette.ColorRole, QtGui.QColor
    p = QtGui.QPalette()
    for rol, color in ((R.Window, FONDO), (R.WindowText, TEXTO), (R.Base, "#0D0D0D"), (R.AlternateBase, "#1A1A1A"),
                       (R.Text, TEXTO), (R.Button, RELIEVE), (R.ButtonText, TEXTO), (R.BrightText, TEXTO),
                       (R.ToolTipBase, "#262626"), (R.ToolTipText, TEXTO), (R.PlaceholderText, "#808080"),
                       (R.Highlight, "#34486A"), (R.HighlightedText, TEXTO), (R.Link, AZUL),
                       (R.Light, "#3D3D3D"), (R.Midlight, "#2E2E2E"), (R.Mid, BORDE), (R.Dark, "#0A0A0A"), (R.Shadow, "#000000")):
        p.setColor(rol, C(color))
    for rol in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(QtGui.QPalette.ColorGroup.Disabled, rol, C("#666666"))
    return p


def aplicar_tema(app):
    """Pone el tema oscuro completo: estilo Fusion (igual en Windows, Linux y Mac), paleta, letra y hoja de estilos."""
    app.setStyle("Fusion")
    app.setPalette(paleta_oscura())
    cargar_fuentes()
    app.setStyleSheet(ESTILO)


def campo_numero(minimo=0, maximo=100000):
    """Caja para escribir un numero, con el mismo margen interior que los demas campos (sin flechas, el
    QSpinBox pegaba el numero al borde)."""
    sb = QtWidgets.QSpinBox()
    sb.setRange(minimo, maximo)
    sb.lineEdit().setTextMargins(10, 0, 10, 0)
    return sb


def centrado(e):
    e.setAlignment(QtCore.Qt.AlignmentFlag.AlignHCenter | QtCore.Qt.AlignmentFlag.AlignVCenter)
    return e


def heroe(rotulo, numero, abajo=None, derecha=None, centro=False, icono_=None):
    """Tarjeta destacada con el numero que importa en grande, como en el PDF: rotulo arriba, numero grande,
    un texto debajo y, si se da, un dato a la derecha alineado con el numero. Con centro=True todo va centrado
    y con mas aire: es la tarjeta principal de una pantalla."""
    caja = Panel()
    if centro:
        caja.setObjectName("premio")
        v = QtWidgets.QVBoxLayout(caja)
        v.setContentsMargins(28, 30, 28, 34)
        v.setSpacing(2)
        if icono_:
            v.addWidget(insignia(icono_, 52), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
            v.addSpacing(14)
        rotulo.setObjectName("heroe_rotulo")
        numero.setObjectName("heroe_numero")
        for w in (rotulo, numero, abajo):
            if w is not None:
                v.addWidget(centrado(w))
        return brillo(caja)
    caja.setObjectName("heroe")
    v = QtWidgets.QVBoxLayout(caja)
    v.setContentsMargins(22, 16, 22, 18)
    v.setSpacing(0)
    rotulo.setObjectName("heroe_rotulo")
    numero.setObjectName("heroe_numero")
    v.addWidget(rotulo)
    h = QtWidgets.QHBoxLayout()
    h.setSpacing(12)
    h.addWidget(numero, 0, QtCore.Qt.AlignmentFlag.AlignBottom)
    h.addStretch(1)
    if derecha is not None:
        h.addWidget(derecha, 0, QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignRight)
    v.addLayout(h)
    if abajo is not None:
        v.addWidget(abajo)
    return caja


def miles(n):
    """1234 -> '1,234'."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def fecha_corta(iso, anio=True):
    """'2026-11-22' -> 'Nov 22, 2026' (o 'Nov 22' sin el ano)."""
    if not iso:
        return "—"
    try:
        d = datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{MESES[d.month - 1]} {d.day}, {d.year}" if anio else f"{MESES[d.month - 1]} {d.day}"


def hace(iso):
    if not iso:
        return "never"
    dias = (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(iso)).days
    return "today" if dias < 1 else ("yesterday" if dias < 2 else f"{dias} days ago")


def texto_hallazgo(h):
    if h["tipo"] == "caida":
        return f"{miles(h['reses'])} fewer cattle than in the {fecha_corta(h['fecha_anterior'])} count ({h['pct']:+.0f}%)"
    if h["tipo"] == "faltan":
        return (f"{miles(h['reses'])} cattle missing without explanation: with the sales, purchases and births logged since "
                f"{fecha_corta(h['fecha_anterior'])} there should be {miles(h['esperadas'])}")
    if h["tipo"] == "sobran":
        return (f"{miles(h['reses'])} more cattle than expected ({miles(h['esperadas'])}): is a birth or a purchase "
                f"missing from the log?")
    return str(h)


def texto_cuadre(q):
    """'61 on Oct 20 + 3 in − 19 out = 45 expected'."""
    partes = [f"{miles(q['base'])} on {fecha_corta(q['fecha_base'])}"]
    if q["entradas"]:
        partes.append(f"+ {miles(q['entradas'])} in")
    if q["salidas"]:
        partes.append(f"− {miles(q['salidas'])} out")
    return " ".join(partes) + f" = {miles(q['esperadas'])} expected"


def etiqueta(texto, nombre=None, envolver=False):
    e = QtWidgets.QLabel(texto)
    if nombre:
        e.setObjectName(nombre)
    e.setWordWrap(envolver)
    return e


def boton(texto, accion=None, nombre="secundario", marcable=False):
    b = QtWidgets.QPushButton(texto)
    b.setObjectName(nombre)
    b.setCheckable(marcable)
    b.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
    if accion:
        b.clicked.connect(accion)
    return b


def tarjeta(*widgets, margen=22):
    t = Panel()
    t.setObjectName("tarjeta")
    lay = QtWidgets.QVBoxLayout(t)
    lay.setContentsMargins(margen, margen, margen, margen)
    lay.setSpacing(10)
    for w in widgets:
        if isinstance(w, QtWidgets.QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return sombra(t)


def dato(rotulo):
    """Tarjeta de resumen: un rotulo y un numero grande. Devuelve (tarjeta, etiqueta del numero)."""
    valor = etiqueta("—", "numero_med")
    t = tarjeta(etiqueta(rotulo.upper(), "rotulo"), valor, margen=20)
    return t, valor


def fila(*widgets, espacio=12):
    lay = QtWidgets.QHBoxLayout()
    lay.setSpacing(espacio)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QtWidgets.QLayout):
            lay.addLayout(w)
        else:
            lay.addWidget(w)
    return lay


def aviso(texto, texto_boton=None, accion=None):
    a = Panel()
    a.setObjectName("aviso")
    lay = QtWidgets.QHBoxLayout(a)
    lay.setContentsMargins(22, 14, 16, 14)
    e = etiqueta(texto, envolver=True)
    lay.addWidget(e, 1)
    if texto_boton:
        lay.addWidget(boton(texto_boton, accion, "enlace"))
    return a


def vaciar(layout):
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide()                           # deleteLater tarda: sin esto el aviso viejo se ve encima
            w.setParent(None)
            w.deleteLater()
        elif it.layout():
            vaciar(it.layout())


def tabla(columnas, derecha=()):
    t = QtWidgets.QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels([c.upper() for c in columnas])
    for i in derecha:                       # el rotulo de una columna de numeros va alineado con los numeros
        t.horizontalHeaderItem(i).setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
    t.setMouseTracking(True)
    t.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(52)
    t.setShowGrid(False)
    t.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
    t.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    t.horizontalHeader().setStretchLastSection(True)
    t.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
    return sombra(t)


def ajustar(t, max_filas=10):
    """La tabla toma el alto de sus filas (sin tarjeta blanca vacia debajo); con muchas filas se desplaza."""
    n = min(t.rowCount(), max_filas)
    alto = t.horizontalHeader().sizeHint().height() + n * t.verticalHeader().defaultSectionSize() + 16
    t.setFixedHeight(alto)


def celda(texto, derecha=False, negrita=False, alerta=False, enlace=False):
    if isinstance(texto, int) and not isinstance(texto, bool):
        texto = miles(texto)
    it = QtWidgets.QTableWidgetItem("" if texto is None else str(texto))
    if enlace:
        it.setForeground(QtGui.QColor(TEXTO))
        f = it.font()
        f.setUnderline(True)
        f.setWeight(QtGui.QFont.Weight.DemiBold)
        it.setFont(f)
    if derecha:
        it.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
    if negrita:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if alerta:
        it.setBackground(QtGui.QColor(FONDO_ROJO))
        it.setForeground(QtGui.QColor(ROJO))
    return it


class Pagina(QtWidgets.QScrollArea):
    """Una pantalla: contenido centrado, con ancho maximo, que se desplaza si no cabe."""

    def __init__(self, ancho=1040):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        fondo = QtWidgets.QWidget()
        fondo.setObjectName("pagina")
        self.setWidget(fondo)
        exterior = QtWidgets.QHBoxLayout(fondo)
        exterior.setContentsMargins(32, 28, 32, 32)
        centro = QtWidgets.QWidget()
        centro.setMaximumWidth(ancho)
        exterior.addStretch(1)
        exterior.addWidget(centro, 100)
        exterior.addStretch(1)
        self.lay = QtWidgets.QVBoxLayout(centro)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(20)


class Barras(QtWidgets.QWidget):
    """Reses en cada conteo: una barra por conteo, la ultima en blanco."""

    def __init__(self):
        super().__init__()
        self.datos = []
        self.setMinimumHeight(190)

    def poner(self, serie, mensual=False):
        self.mensual = mensual
        self.datos = serie[-12:] if mensual else serie[-8:]          # [(fecha o 'AAAA-MM', total)]
        self.update()

    def paintEvent(self, _):
        if not self.datos:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        alto, base_y = self.height() - 56, self.height() - 26
        maximo = max(t for _, t in self.datos) or 1
        paso = min(84.0, (self.width() - 16) / max(len(self.datos), 1))
        ancho = min(56.0, paso * 0.68)
        for i, (fecha, total) in enumerate(self.datos):
            x = 8 + i * paso
            h = max(4, int(alto * total / maximo))
            ultima = i == len(self.datos) - 1
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            barra = QtCore.QRectF(x, base_y - h, ancho, h)
            g = QtGui.QLinearGradient(barra.topLeft(), barra.bottomLeft())      # la ultima brilla; las demas son vidrio
            g.setColorAt(0.0, QtGui.QColor("#FFFFFF" if ultima else "#5C6470"))
            g.setColorAt(1.0, QtGui.QColor("#9DBDF2" if ultima else "#2A2E35"))
            p.setBrush(g)
            p.drawRoundedRect(barra, 7, 7)
            p.setPen(QtGui.QColor(TEXTO))
            f = p.font(); f.setBold(True); p.setFont(f)
            p.drawText(QtCore.QRectF(x - 14, base_y - h - 22, ancho + 28, 20), QtCore.Qt.AlignmentFlag.AlignCenter, miles(total))
            f.setBold(False); p.setFont(f)
            p.setPen(QtGui.QColor(GRIS))
            d = (MESES[int(fecha[5:7]) - 1] + " " + fecha[2:4]) if getattr(self, "mensual", False) else fecha_corta(fecha, anio=False)
            p.drawText(QtCore.QRectF(x - 14, base_y + 4, ancho + 28, 20), QtCore.Qt.AlignmentFlag.AlignCenter, d)


# ------------------------------------------------------------------ Fincas

class PaginaFincas(Pagina):
    def __init__(self, v):
        super().__init__()
        self.v = v
        self.titulo = etiqueta("", "titulo")
        self.sub = etiqueta("", "sub")
        self.b_nuevo = boton("New count", lambda: self.v.nuevo_conteo(), "primario")
        izq = QtWidgets.QVBoxLayout()
        izq.setSpacing(4)
        izq.addWidget(self.titulo)
        izq.addWidget(self.sub)
        self.lay.addLayout(fila(izq, None, self.b_nuevo))
        (t1, self.d_fincas), (t2, self.d_reses), (t3, self.d_hallazgos) = dato("Ranches"), dato("Cattle"), dato("Ranches with findings")
        self.datos = fila(t1, t2, t3, espacio=16)
        self.lay.addLayout(self.datos)
        self.avisos = QtWidgets.QVBoxLayout()
        self.avisos.setSpacing(8)
        self.lay.addLayout(self.avisos)
        self.tabla = tabla(["Ranch", "Last count", "Date", "Change"], derecha=(1,))
        self.tabla.cellClicked.connect(lambda f, _: self.v.abrir_finca(self.filas[f]["id"]))
        self.tabla.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.lay.addWidget(self.tabla)
        self.vacio = tarjeta(etiqueta("No ranch yet", "destacado"),
                             etiqueta("Record the flight with the drone, copy the video to the computer and start with “New count”. "
                                      "Your ranch shows up here with its last count.", "sub", True), margen=28)
        self.lay.addWidget(self.vacio)
        self.lay.addStretch(1)
        self.filas = []

    def refrescar(self):
        b = self.v.base
        self.filas = b.resumen_fincas("")
        total = sum(r["ultimo"] or 0 for r in self.filas)
        self.titulo.setText("Your ranch" if b.una_finca() else "Ranches")
        n = len(self.filas)
        pr = b.precision()
        self.sub.setText("Last count of each ranch"
                         + (f" · error medido contra corral: {pr['error_medio_pct']:.1f} %" if pr else ""))
        vaciar(self.avisos)
        con = [(r, b.hallazgos(r["id"])) for r in self.filas]
        con = [(r, h) for r, h in con if h]
        self.d_fincas.setText(miles(n))
        self.d_reses.setText(miles(total))
        self.d_hallazgos.setText(miles(len(con)))
        for i in range(self.datos.count()):
            self.datos.itemAt(i).widget().setVisible(n > 0)
        for r, h in con[:3]:
            self.avisos.addWidget(aviso(f"{r['finca']}: the last count found {texto_hallazgo(h[0])}.",
                                        "See findings", lambda _=False, i=r["id"]: self.v.abrir_finca(i)))
        if len(con) > 3:
            self.avisos.addWidget(etiqueta(f"And {len(con) - 3} more ranches with findings.", "gris"))
        self.tabla.setRowCount(n)
        for i, r in enumerate(self.filas):
            pct = r["cambio_pct"]
            alerta = pct is not None and pct <= -CAIDA_ALERTA
            cambio = "—" if r["cambio"] is None else ("No change" if r["cambio"] == 0 else
                                                      f"{'Down' if r['cambio'] < 0 else 'Up'} {miles(abs(r['cambio']))} · {pct:+.0f} %")
            self.tabla.setItem(i, 0, celda(r["finca"], negrita=True))
            self.tabla.setItem(i, 1, celda("—" if r["ultimo"] is None else r["ultimo"], derecha=True, negrita=True))
            self.tabla.setItem(i, 2, celda("No counts" if r["fecha"] is None else fecha_corta(r["fecha"])))
            self.tabla.setItem(i, 3, celda(cambio, alerta=alerta))
        self.tabla.resizeColumnsToContents()
        for col, minimo in ((0, 280), (1, 140), (2, 150)):
            self.tabla.setColumnWidth(col, max(minimo, self.tabla.columnWidth(col) + 24))
        ajustar(self.tabla, 12)
        self.tabla.setVisible(n > 0)
        self.vacio.setVisible(n == 0)


class DialogoMovimiento(QtWidgets.QDialog):
    """Anotar una venta, compra, nacimiento, muerte o traslado: con eso AGI cuadra el inventario."""

    def __init__(self, padre, finca):
        super().__init__(padre)
        self.setWindowTitle("Log movement")
        self.setMinimumWidth(460)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(8)
        lay.addWidget(etiqueta("Log movement", "entrar_titulo"))
        lay.addWidget(etiqueta(f"{finca}. What comes into or leaves the ranch between one count and the next.", "sub", True))
        lay.addSpacing(8)
        self.tipo = QtWidgets.QComboBox()
        for clave, (nombre, signo) in datos.TIPOS_MOVIMIENTO.items():
            self.tipo.addItem(f"{nombre}  ({'in' if signo > 0 else 'out'})", clave)
        self.cantidad = campo_numero(1)
        self.fecha = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("MMM d, yyyy")
        self.fecha.setMaximumDate(QtCore.QDate.currentDate())
        self.nota = QtWidgets.QLineEdit()
        self.nota.setPlaceholderText("Optional: buyer, permit, cause…")
        g = QtWidgets.QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(6)
        for i, (rot, w) in enumerate((("Movement", self.tipo), ("Cattle", self.cantidad), ("Date", self.fecha))):
            g.addWidget(etiqueta(rot, "campo"), 0, i)
            g.addWidget(w, 1, i)
        g.setColumnStretch(0, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(2, 2)
        lay.addLayout(g)
        lay.addWidget(etiqueta("Note", "campo"))
        lay.addWidget(self.nota)
        self.error = etiqueta("", "error", True)
        lay.addWidget(self.error)
        lay.addLayout(fila(None, boton("Cancel", self.reject, "plano"), boton("Log", self.accept, "primario")))

    def valores(self):
        return (self.fecha.date().toString("yyyy-MM-dd"), self.tipo.currentData(), self.cantidad.value(), self.nota.text())


class PaginaFinca(Pagina):
    def __init__(self, v):
        super().__init__()
        self.v = v
        self.finca_id = None
        self.b_volver = boton("‹  Ranches", lambda: self.v.ir("fincas"), "plano")
        self.lay.addLayout(fila(self.b_volver, None))
        self.titulo = etiqueta("", "titulo")
        self.sub = etiqueta("", "sub")
        self.b_excel = boton("Export to Excel", self.exportar_excel)
        self.b_mov = boton("Log movement", self.anotar)
        self.b_nuevo = boton("New count", lambda: self.v.nuevo_conteo(self.finca_id), "primario")
        izq = QtWidgets.QVBoxLayout()
        izq.setSpacing(4)
        izq.addWidget(self.titulo)
        izq.addWidget(self.sub)
        self.lay.addLayout(fila(izq, None, self.b_excel, self.b_mov, self.b_nuevo))
        self.avisos = QtWidgets.QVBoxLayout()
        self.avisos.setSpacing(8)
        self.lay.addLayout(self.avisos)
        # ultimo conteo y grafica
        self.ultimo_fecha = etiqueta("")
        self.ultimo = etiqueta("—", "heroe_numero")
        self.esperadas = centrado(etiqueta("", None, True))
        self.barras = Barras()
        self.b_g_conteos = boton("Counts", lambda: self.grafica(False), "pestana", marcable=True)
        self.b_g_meses = boton("By month", lambda: self.grafica(True), "pestana", marcable=True)
        cab_g = fila(etiqueta("Cattle per count", "gris"), None, self.b_g_conteos, self.b_g_meses, espacio=4)
        self.t_grafica = cab_g.itemAt(0).widget()
        t_ultimo = heroe(self.ultimo_fecha, self.ultimo, etiqueta("cattle"), centro=True, icono_="res")
        t_ultimo.layout().insertStretch(0, 1)
        t_ultimo.layout().addWidget(self.esperadas)
        t_ultimo.layout().addStretch(1)
        fila_g = fila(t_ultimo, tarjeta(cab_g, self.barras), espacio=16)
        fila_g.setStretch(0, 1)
        fila_g.setStretch(1, 1)
        self.lay.addLayout(fila_g)
        # cuadre de inventario
        self.c_pasos = []
        pasos = QtWidgets.QHBoxLayout()
        pasos.setSpacing(10)
        for i in range(5):
            caja = Panel()
            caja.setObjectName("caja_oscura" if i == 4 else "caja")
            c = QtWidgets.QVBoxLayout(caja)
            c.setContentsMargins(14, 10, 14, 12)
            c.setSpacing(2)
            rot, val = centrado(etiqueta("", "gris")), centrado(etiqueta("", "numero_med"))
            c.addWidget(rot)
            c.addWidget(val)
            pasos.addWidget(caja, 1)
            self.c_pasos.append((rot, val))
        self.c_estado = etiqueta("", None, True)
        self.c_detalle = etiqueta("", "gris", True)
        centrado(self.c_estado)
        centrado(self.c_detalle)
        self.t_cuadre = tarjeta(fila(None, insignia("cuadre", 44), None), centrado(etiqueta("Inventory reconciliation", "h3")),
                                centrado(etiqueta("The previous count, plus what came in, minus what went out: that's how AGI knows how many "
                                                  "cattle there should be.", "gris", True)), pasos, self.c_estado, self.c_detalle, margen=28)
        self.t_cuadre.layout().setSpacing(12)
        self.lay.addWidget(self.t_cuadre)
        # potreros
        self.t_potreros_tabla = tabla(["Paddock", "Last count", "Cattle"], derecha=(2,))
        self.t_potreros = QtWidgets.QWidget()
        lp = QtWidgets.QVBoxLayout(self.t_potreros)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(10)
        lp.addWidget(centrado(etiqueta("By paddock", "h3")))
        lp.addWidget(self.t_potreros_tabla)
        self.lay.addWidget(self.t_potreros)
        # conteos
        self.lay.addWidget(centrado(etiqueta("Counts", "h3")))
        self.tabla = tabla(["Flight date", "Paddock", "Cattle", "Corral count", "Difference", "Counted by", "Report"], derecha=(2, 3))
        self.tabla.cellClicked.connect(self.clic)
        self.tabla.cellEntered.connect(lambda f, c: self.tabla.viewport().setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor if c == 6 and self.tabla.item(f, 6) and self.tabla.item(f, 6).text() == "Open PDF"
            else QtCore.Qt.CursorShape.ArrowCursor))
        self.lay.addWidget(self.tabla)
        # movimientos
        self.lay.addWidget(centrado(etiqueta("Movements", "h3")))
        self.t_movs = tabla(["Date", "Movement", "Cattle", "Note", "Logged by", ""], derecha=(2,))
        self.t_movs.cellClicked.connect(self.clic_mov)
        self.t_movs.cellEntered.connect(lambda f, c: self.t_movs.viewport().setCursor(
            QtCore.Qt.CursorShape.PointingHandCursor if c == 5 and self.t_movs.item(f, 5) and self.t_movs.item(f, 5).text()
            else QtCore.Qt.CursorShape.ArrowCursor))
        self.lay.addWidget(self.t_movs)
        self.movs_vacio = tarjeta(etiqueta("No movements logged yet. Log sales, purchases, births and deaths: "
                                           "with them AGI tells you if any animal is missing between one count and the next.", "gris", True))
        self.lay.addWidget(self.movs_vacio)
        self.lay.addStretch(1)
        self.conteos, self.movs, self.mensual = [], [], False

    def abrir(self, finca_id):
        self.finca_id = finca_id
        b = self.v.base
        f = b.datos_finca(finca_id)
        self.titulo.setText(f["nombre"])
        partes = [x for x in (f["propietario"], f["municipio"]) if x]
        self.sub.setText(" · ".join(partes) or "—")
        propia = not f["cliente"]
        self.b_nuevo.setVisible(propia)
        self.b_mov.setVisible(propia)
        self.b_excel.setVisible(b.rol == "admin")
        sola = b.una_finca() and propia
        self.b_volver.setVisible(not sola)
        vaciar(self.avisos)
        hall = b.hallazgos(finca_id)
        if hall:
            self.avisos.addWidget(centrado(etiqueta("Findings from the last count", "h3")))
        for h in hall:
            self.avisos.addWidget(aviso(texto_hallazgo(h)[0].upper() + texto_hallazgo(h)[1:]))
        hist = b.historial(finca_id)
        if hist:
            pots = hist[-1][6]
            self.ultimo.setText(miles(hist[-1][1]))
            self.ultimo_fecha.setText(f"Last count · {fecha_corta(hist[-1][0])}"
                                      + (f" · {len(pots)} paddock{'s' if len(pots) != 1 else ''}" if pots else ""))
        else:
            self.ultimo.setText("—")
            self.ultimo_fecha.setText("No counts yet")
        esp = b.esperadas_hoy(finca_id)
        self.esperadas.setVisible(bool(esp and esp[1]))
        if esp and esp[1]:
            pl = "s" if esp[1] != 1 else ""
            self.esperadas.setText(f"Expected today: {miles(esp[0])} · {esp[1]} movement{pl} logged after the count")
        self.grafica(self.mensual)
        self._cuadre()
        # potreros
        pp = b.por_potrero(finca_id)
        self.t_potreros.setVisible(bool(pp))
        t = self.t_potreros_tabla
        t.setRowCount(len(pp))
        for i, r in enumerate(pp):
            t.setItem(i, 0, celda(r["potrero"], negrita=True))
            t.setItem(i, 1, celda(fecha_corta(r["fecha"])))
            t.setItem(i, 2, celda(r["total"], derecha=True, negrita=True))
        t.setColumnWidth(0, 300)
        t.setColumnWidth(1, 200)
        ajustar(t, 8)
        # conteos
        self.conteos = b.conteos_de(finca_id)
        self.tabla.setColumnHidden(1, not pp)
        self.tabla.setRowCount(len(self.conteos))
        for i, c in enumerate(self.conteos):
            ref = c["referencia"]
            self.tabla.setItem(i, 0, celda(fecha_corta(c["fecha_vuelo"])))
            self.tabla.setItem(i, 1, celda(c["potrero"] or "Whole ranch"))
            self.tabla.setItem(i, 2, celda(c["total"], derecha=True, negrita=True))
            self.tabla.setItem(i, 3, celda("—" if not ref else ref, derecha=True))
            self.tabla.setItem(i, 4, celda("—" if not ref else f"{c['total'] - ref:+d} ({100.0 * (c['total'] - ref) / ref:+.1f} %)".replace(".", ",")))
            self.tabla.setItem(i, 5, celda(c["usuario"]))
            hay_pdf = bool(b.ruta_reporte(c["pdf_ruta"]))
            self.tabla.setItem(i, 6, celda("Open PDF" if hay_pdf else "—", enlace=hay_pdf))
        self.tabla.resizeColumnsToContents()
        for col in range(6):
            self.tabla.setColumnWidth(col, max(120, self.tabla.columnWidth(col) + 24))
        ajustar(self.tabla, 12)
        # movimientos
        self.movs = b.movimientos(finca_id)
        t = self.t_movs
        t.setRowCount(len(self.movs))
        admin = b.rol == "admin" and propia
        for i, m in enumerate(self.movs):
            t.setItem(i, 0, celda(fecha_corta(m["fecha"])))
            t.setItem(i, 1, celda(m["nombre"]))
            it = celda(f"{'+' if m['signo'] > 0 else '−'}{miles(m['cantidad'])}", derecha=True, negrita=True)
            it.setForeground(QtGui.QColor(VERDE if m["signo"] > 0 else ROJO))
            t.setItem(i, 2, it)
            t.setItem(i, 3, celda(m["nota"] or "—"))
            t.setItem(i, 4, celda(m["usuario"]))
            t.setItem(i, 5, celda("Remove" if admin and not m["importado"] else "", enlace=admin and not m["importado"]))
        for col, w in enumerate((150, 220, 110, 260, 130)):
            t.setColumnWidth(col, w)
        ajustar(t, 10)
        t.setVisible(bool(self.movs))
        self.movs_vacio.setVisible(not self.movs)

    def grafica(self, mensual):
        self.mensual = mensual
        self.b_g_conteos.setChecked(not mensual)
        self.b_g_meses.setChecked(mensual)
        if self.finca_id is None:
            return
        b = self.v.base
        if mensual:
            self.t_grafica.setText("Cattle at each month's close")
            self.barras.poner(b.por_mes(self.finca_id), mensual=True)
        else:
            self.t_grafica.setText("Cattle per count")
            self.barras.poner([(x[0], x[1]) for x in b.historial(self.finca_id)])

    def _cuadre(self):
        q = self.v.base.cuadre(self.finca_id)
        self.t_cuadre.setVisible(bool(q and q["movimientos"]))
        if not (q and q["movimientos"]):
            return
        valores = [(f"Count of {fecha_corta(q['fecha_base'], anio=False)}", miles(q["base"])),
                   ("Came in", f"+{miles(q['entradas'])}"), ("Went out", f"−{miles(q['salidas'])}"),
                   ("Expected", miles(q["esperadas"])), ("AGI counted", miles(q["contadas"]))]
        for (rot, val), (r, v) in zip(self.c_pasos, valores):
            rot.setText(r)
            val.setText(v)
        margen = max(datos.MARGEN_CUADRE, round(q["esperadas"] * CAIDA_ALERTA / 100.0))
        dif = q["diferencia"]
        if abs(dif) < margen:
            self.c_estado.setText(f"✓  Reconciled: the difference ({dif:+d}) is within the count's margin of error.")
            self.c_estado.setStyleSheet(f"color: {VERDE}; font-weight: 600;")
        elif dif < 0:
            self.c_estado.setText(f"{miles(-dif)} cattle missing without explanation. Check whether a sale, a death or "
                                  "a transfer is missing from the log; if not, it's worth riding the ranch.")
            self.c_estado.setStyleSheet(f"color: {ROJO}; font-weight: 600;")
        else:
            self.c_estado.setText(f"{miles(dif)} more cattle than expected: a birth or a purchase may be missing from the log.")
            self.c_estado.setStyleSheet(f"color: {AZUL}; font-weight: 600;")
        self.c_detalle.setText("Between the two counts: " + ", ".join(
            f"{miles(n)} {datos.PLURAL_MOVIMIENTO[k] if n != 1 else datos.TIPOS_MOVIMIENTO[k][0].lower()}"
            for k, n in q["detalle"].items()) + ".")

    def anotar(self):
        d = DialogoMovimiento(self, self.titulo.text())
        while d.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            try:
                self.v.base.anotar_movimiento(self.finca_id, *d.valores())
            except Exception as err:  # noqa: BLE001 - se muestra al usuario
                d.error.setText(str(err))
                continue
            break
        self.abrir(self.finca_id)

    def clic_mov(self, f, col):
        m = self.movs[f]
        if col != 5 or not self.t_movs.item(f, 5).text():
            return
        motivo, ok = QtWidgets.QInputDialog.getText(self, "Remove movement",
                                                    f"{m['nombre']} of {m['cantidad']} on {fecha_corta(m['fecha'])}.\n"
                                                    "Why are you removing it? It's recorded in the audit log.")
        if ok and motivo.strip():
            self.v.base.borrar_movimiento(m["id"], motivo)
            self.abrir(self.finca_id)

    def exportar_excel(self):
        r = QtWidgets.QMessageBox.question(self, "Export to Excel", "The Excel file is NOT encrypted: anyone who has it can see the "
                                           "inventory of this ranch. Export?")
        if r != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        nombre = f"Inventory {self.titulo.text()} {datetime.date.today().isoformat()}.xlsx"
        ruta, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Excel", os.path.join(os.path.expanduser("~"), nombre),
                                                        "Excel (*.xlsx)")
        if ruta:
            self.guardar_excel(ruta)

    def guardar_excel(self, ruta):
        try:
            excel.exportar(self.v.base, ruta, self.finca_id)
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            QtWidgets.QMessageBox.warning(self, "Could not export", str(err))
            return None
        self.v.statusBar().showMessage(f"Excel saved: {ruta}", 15000)
        return ruta

    def clic(self, f, col):
        c = self.conteos[f]
        ruta = self.v.base.ruta_reporte(c["pdf_ruta"])
        if col == 6 and ruta:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(ruta))


# ------------------------------------------------------------------ Contar

class PaginaContar(QtWidgets.QWidget):
    """Tres pasos: Video, Revisar, Reporte."""

    def __init__(self, v):
        super().__init__()
        self.setObjectName("pagina")
        self.v = v
        self.fotos, self.actual, self.carpeta = [], -1, ""
        self.deshacer_pila, self.hilo, self.escala, self.reintento = [], None, 1.0, False
        self._fincas = {}
        self.pasos, self.pasos_n = [], []
        cab = QtWidgets.QHBoxLayout()
        cab.setSpacing(10)
        cab.setContentsMargins(32, 20, 32, 4)
        for nombre in ("Video", "Review", "Report"):
            n = etiqueta("", "paso_n")
            n.setFixedSize(26, 26)
            n.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            e = etiqueta(nombre, "paso")
            self.pasos_n.append(n)
            self.pasos.append(e)
            cab.addWidget(n)
            cab.addWidget(e)
            cab.addSpacing(22)
        cab.addStretch(1)
        self.pila = QtWidgets.QStackedWidget()
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(cab)
        lay.addWidget(self.pila, 1)
        self._paso1()
        self._paso2()
        self._paso3()
        self.poner_paso(0)

    def poner_paso(self, n):
        for i, (e, num) in enumerate(zip(self.pasos, self.pasos_n)):
            estado = "hecho" if i < n else ("actual" if i == n else "pendiente")
            num.setText("✓" if i < n else str(i + 1))
            for w in (e, num):                      # el estilo depende de la propiedad: hay que repintar
                w.setProperty("estado", estado)
                w.style().unpolish(w)
                w.style().polish(w)
        self.pila.setCurrentIndex(n)

    # ---- paso 1
    def _paso1(self):
        p = Pagina(720)
        self.finca = QtWidgets.QComboBox()
        self.finca.setEditable(True)
        self.finca.lineEdit().setPlaceholderText("Ranch name")
        self.finca.activated.connect(self._eligio_finca)
        self.finca.editTextChanged.connect(lambda _: self._validar1())
        self.propietario = QtWidgets.QLineEdit()
        self.propietario.setPlaceholderText("Owner")
        self.fecha = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.fecha.setCalendarPopup(True)
        self.fecha.setDisplayFormat("MMM d, yyyy")
        self.potrero = QtWidgets.QComboBox()
        self.potrero.setEditable(True)
        self.potrero.lineEdit().setPlaceholderText("Whole ranch")
        self.carpeta_txt = etiqueta("You haven't chosen the video yet.", "gris", True)
        self.fotos_txt = etiqueta("No video", "destacado")
        self.videos, self.extractor, self.info, self.union = [], None, {}, None
        self.estado1 = etiqueta("", "gris", True)
        self.progreso = QtWidgets.QProgressBar()
        self.progreso.setVisible(False)
        self.b_contar = boton("Count", self.contar, "primario")
        form = QtWidgets.QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(6)
        for col, (rot, w) in enumerate((("Ranch", self.finca), ("Owner", self.propietario), ("Flight date", self.fecha))):
            form.addWidget(etiqueta(rot, "gris"), 0, col)
            form.addWidget(w, 1, col)
        self.finca_nota = etiqueta("This account belongs to this ranch: counts are only saved under its name.", "gris", True)
        form.addWidget(self.finca_nota, 4, 0, 1, 3)
        form.addWidget(etiqueta("Paddock (optional)", "gris"), 2, 0)
        form.addWidget(self.potrero, 3, 0)
        form.addWidget(etiqueta("Leave it empty if the flight covered the whole ranch. If you count by paddock, fly them all the "
                                "same day: AGI adds up that day's paddocks.", "gris", True), 3, 1, 1, 2)
        form.setRowMinimumHeight(2, 28)
        form.setColumnStretch(0, 3)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(2, 2)
        zona = QtWidgets.QVBoxLayout()
        zona.setSpacing(2)
        zona.addWidget(self.fotos_txt)
        zona.addWidget(self.carpeta_txt)
        p.lay.addLayout(fila(None, insignia("video", 52), None))
        p.lay.addWidget(centrado(etiqueta("New count", "h2")))
        p.lay.addWidget(centrado(etiqueta("Choose the ranch and the flight video.", "h2_sub")))
        p.lay.addWidget(tarjeta(form, etiqueta("Flight video", "gris"),
                                fila(zona, None, boton("Choose videos", self.elegir_video)),
                                etiqueta("Choose one or more videos of the same flight. AGI never counts the same animal twice.",
                                         "gris", True),
                                self.progreso, self.estado1,
                                fila(None, boton("Cancel", self.v.inicio, "plano"), self.b_contar)))
        p.lay.addStretch(1)
        self.pila.addWidget(p)

    def empezar(self, finca_id=None):
        """Deja el asistente limpio. Con finca_id, la finca ya viene elegida."""
        self._cerrar_video()
        self.fotos, self.actual, self.carpeta, self.deshacer_pila = [], -1, "", []
        self.escala, self.reintento = 1.0, False
        self.videos, self.info, self.union = [], {}, None
        self.fotos_txt.setText("No video")
        self.carpeta_txt.setText("You haven't chosen the video yet.")
        b = self.v.base
        self._fincas = {nombre: prop for _, nombre, prop, _, _ in b.fincas("")}
        self.finca.blockSignals(True)
        self.finca.clear()
        self.finca.addItems(sorted(self._fincas))
        self.finca.setEditText("")
        self.propietario.clear()
        self.potrero.clear()
        self.potrero.setEditText("")
        propia = b.finca_propia() if b.una_finca() else None
        if propia is not None:
            finca_id = propia                       # una cuenta, una finca: no se puede guardar a nombre de otra
        bloqueada = propia is not None
        self.finca.setEnabled(not bloqueada)
        self.propietario.setReadOnly(bloqueada)
        self.propietario.setEnabled(not bloqueada)
        self.finca_nota.setVisible(bloqueada)
        if finca_id is not None:
            f = b.datos_finca(finca_id)
            self.finca.setEditText(f["nombre"])
            self.propietario.setText(f["propietario"])
            self._poner_potreros()
        self.finca.blockSignals(False)
        self.fecha.setDate(QtCore.QDate.currentDate())
        self.fotos_txt.setText("No video")
        self.carpeta_txt.setText("You haven't chosen the video yet.")
        self.estado1.setText("")
        self.progreso.setVisible(False)
        self.referencia.setValue(0)
        self._validar1()
        self.poner_paso(0)

    def _eligio_finca(self, _=None):
        prop = self._fincas.get(self.finca.currentText())
        if prop is not None:
            self.propietario.setText(prop)
        self._poner_potreros()

    def _finca_id(self):
        nombre, prop = self.finca.currentText().strip(), self.propietario.text().strip()
        return next((fid for fid, n, p, _, _ in self.v.base.fincas("") if n == nombre and p == prop), None)

    def _poner_potreros(self):
        fid = self._finca_id()
        self.potrero.clear()
        if fid is not None:
            self.potrero.addItems(self.v.base.potreros(fid))
        self.potrero.setEditText("")

    def potrero_elegido(self):
        return self.potrero.currentText().strip()

    def _validar1(self):
        self.b_contar.setEnabled(bool(self.fotos) and bool(self.finca.currentText().strip()) and self.hilo is None
                                 and self.extractor is None)

    def elegir_video(self):
        filtro = "Drone video (" + " ".join("*" + e for e in vuelo.EXT_VIDEO) + ")"
        rutas, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Flight videos (one or more)", "", filtro)
        if rutas:
            self.poner_videos(sorted(rutas))

    def poner_video(self, ruta):
        self.poner_videos([ruta])

    def poner_videos(self, rutas):
        """Lee los videos: saca un punto de conteo cada vez que el dron avanza media imagen y los une."""
        if self.extractor is not None:
            self.extractor.cancelar = True
            self.extractor.wait(5000)
            self.extractor = None
        self.videos = list(rutas)
        base = os.path.splitext(self.videos[0])[0]
        carpeta = base + ("_conteo" if len(self.videos) == 1 else f"_conteo_{len(self.videos)}_videos")
        info = vuelo.leer(carpeta)
        if info.get("union") and [v["archivo"] for v in info["videos"]] == [os.path.basename(r) for r in self.videos]:
            return self._video_listo(carpeta, 0.0, 0)          # ya se habian leido: se continua donde iba
        self.fotos, self.info, self.union = [], {}, None
        self.fotos_txt.setText("Reading " + ("the video…" if len(self.videos) == 1 else f"{len(self.videos)} videos…"))
        self.carpeta_txt.setText(self._nombres_videos())
        self.estado1.setText("")
        self.progreso.setVisible(True)
        self.progreso.setRange(0, 0)
        self.extractor = Extractor(self.videos, carpeta)
        self.extractor.avance.connect(lambda hecho, total: (self.progreso.setRange(0, max(total, 1)), self.progreso.setValue(hecho)))
        self.extractor.uniendo.connect(lambda hecho, total: (self.fotos_txt.setText("Stitching the images…"),
                                                            self.progreso.setRange(0, max(total, 1)), self.progreso.setValue(hecho)))
        self.extractor.listo.connect(self._video_listo)
        self.extractor.fallo.connect(self._video_fallo)
        self._validar1()
        self.extractor.start()

    def _nombres_videos(self):
        nombres = [os.path.basename(r) for r in self.videos]
        return ", ".join(nombres[:3]) + (f" and {len(nombres) - 3} more" if len(nombres) > 3 else "")

    def _video_listo(self, carpeta, duracion, cuantas):
        self.extractor = None
        self.progreso.setVisible(False)
        self.poner_carpeta(carpeta)
        self.carpeta_txt.setText(self._nombres_videos())
        n, nv = len(self.fotos), len(self.videos)
        self.fotos_txt.setText(("1 video" if nv == 1 else f"{nv} videos") + " · " + ("1 count point" if n == 1 else f"{n} count points"))
        if cuantas:
            self.v.base.anotar("video_cargado", {"videos": [os.path.basename(r) for r in self.videos], "duracion_s": round(duracion),
                                                 "puntos": cuantas, "partes": self.union["grupos"] if self.union else None})

    def _video_fallo(self, mensaje):
        self.extractor = None
        self.progreso.setVisible(False)
        self.fotos = []
        self.fotos_txt.setText("No video")
        self.estado1.setText(mensaje)
        self._validar1()

    def poner_carpeta(self, carpeta):
        rutas = sorted(os.path.join(carpeta, f) for f in os.listdir(carpeta)
                       if f.lower().endswith(contar.EXT) and not f.lower().endswith(("_conteo.jpg", "_t.jpg")))
        self.carpeta = carpeta
        self.info = vuelo.leer(carpeta)
        self.union = vuelo.leer_union(self.info)
        self.fotos = [Foto(r) for r in rutas]
        self.fotos_txt.setText(f"{len(self.fotos)} photo{'s' if len(self.fotos) != 1 else ''}" if self.fotos else "No images in that folder")
        self.carpeta_txt.setText(carpeta)
        self._cargar_revision()
        if any(f.procesada for f in self.fotos):
            self.estado1.setText("This folder already had a saved review: picking up where it left off.")
        self._validar1()

    def contar(self):
        pendientes = [i for i, f in enumerate(self.fotos) if not f.procesada]
        if not pendientes:
            return self._a_revisar()
        if not os.path.exists(self.v.modelo):
            self.estado1.setText(f"Can't find the model: {self.v.modelo}")
            return
        self.hilo = Detector(self.fotos, pendientes, self.v.modelo, self.escala)
        self.hilo.avance.connect(self._avance)
        self.hilo.foto_lista.connect(self._foto_lista)
        self.hilo.foto_danada.connect(self._foto_danada)
        self.hilo.fallo.connect(lambda m: self.estado1.setText(f"Could not count: {m}"))
        self.hilo.finished.connect(self._fin)
        self.progreso.setVisible(True)
        self.progreso.setRange(0, len(pendientes))
        self._validar1()
        self.hilo.start()

    def _avance(self, n, total, nombre):
        self.progreso.setValue(n)
        if nombre:
            self.estado1.setText(f"Counting image {n + 1} of {total}…")

    def _foto_lista(self, i, cajas, punt):
        f = self.fotos[i]
        f.dets = [d for d in f.dets if d["origen"] == "manual"] + [
            {"caja": [float(v) for v in c], "conf": float(s), "origen": "ia", "quitada": False} for c, s in zip(cajas, punt)]
        f.procesada = True

    def _foto_danada(self, i):
        self.fotos[i].danada = True
        self.fotos[i].procesada = True

    def _fin(self):
        self.hilo = None
        self.progreso.setVisible(False)
        malas = [f.nombre for f in self.fotos if f.danada]
        if malas:                       # una foto que no abre no puede contarse: se saca y se dice
            self.fotos = [f for f in self.fotos if not f.danada]
            self.fotos_txt.setText(f"{len(self.fotos)} photo{'s' if len(self.fotos) != 1 else ''}")
            self.v.base.anotar("fotos_ilegibles", {"cuantas": len(malas), "nombres": malas[:10]})
            lista = ", ".join(malas[:5]) + ("…" if len(malas) > 5 else "")
            QtWidgets.QMessageBox.warning(self, "Images that could not be read",
                                          ("1 image could not be read and was left out " if len(malas) == 1 else f"{len(malas)} images could not be read and were left out ") +
                                          f"of the count: {lista}.\n\nIf cattle are missing from the total, copy the video again "
                                          "from the drone's card.")
            if not self.fotos:
                self.estado1.setText("None of the video's images could be read.")
                self._validar1()
                return
        # el modelo espera reses de 30 a 60 px: si salieron mucho mas grandes, se repite una vez reduciendo la foto
        lados = [max(d["caja"][2] - d["caja"][0], d["caja"][3] - d["caja"][1])
                 for f in self.fotos for d in f.dets if d["origen"] == "ia" and d["conf"] >= CONF_DEFECTO]
        if lados and not self.reintento:
            tam = float(np.median(lados)) * self.escala
            if tam > 75:
                self.reintento = True
                self.escala = max(0.1, round(self.escala * 45 / tam, 2))
                for f in self.fotos:
                    f.procesada = False
                self.estado1.setText("The cattle look large in this video: adjusting and counting again…")
                return self.contar()
        self.numerar()
        self.guardar_revision()
        self._validar1()
        if any(f.procesada for f in self.fotos):
            self._a_revisar()

    def _por_punto(self):
        """(rutas, detecciones) en el orden de los puntos del vuelo, como los dejo unir()."""
        puntos = self.info.get("puntos") or []
        por_nombre = {f.nombre: f for f in self.fotos}
        rutas = [os.path.join(self.carpeta, p["nombre"]) for p in puntos]
        dets = [por_nombre[p["nombre"]].dets if p["nombre"] in por_nombre else [] for p in puntos]
        return rutas, dets

    def numerar(self):
        """Cada res recibe un numero fijo; la que ya se vio en otro punto queda como repetida. Devuelve cuantas hay."""
        if self.union is not None and self.info.get("puntos"):
            _, dets = self._por_punto()
            return vuelo.numerar(dets, self.union, CONF_DEFECTO, self.info["puntos"])
        return vuelo.numerar([f.dets for f in self.fotos], None, CONF_DEFECTO)

    # ---- paso 2
    def _paso2(self):
        w = QtWidgets.QWidget()
        w.setObjectName("pagina")
        self.visor = Visor()
        self.visor.agregada.connect(self.agregar)
        self.visor.quitada.connect(self.quitar)
        self.foto_txt = etiqueta("", "gris")
        self.n_foto = etiqueta("0", "heroe_numero")
        self.llevas = etiqueta("0", "heroe_valor")
        self.llevas.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        llevas = QtWidgets.QWidget()
        ll = QtWidgets.QVBoxLayout(llevas)
        ll.setContentsMargins(0, 0, 0, 10)
        ll.setSpacing(0)
        t_llevas = etiqueta("so far", None)
        t_llevas.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        ll.addWidget(t_llevas)
        ll.addWidget(self.llevas)
        self.heroe_rev = heroe(etiqueta("NEW CATTLE AT THIS POINT"), self.n_foto, None, llevas)
        self.leyenda = etiqueta("", "resumen_rev", True)
        self.leyenda.setTextFormat(QtCore.Qt.TextFormat.RichText)
        self.b_agregar = boton("Add animal", lambda: self.herramienta("agregar"), marcable=True)
        self.b_quitar = boton("Remove box", lambda: self.herramienta("quitar"), marcable=True)
        self.b_deshacer = boton("Undo", self.deshacer, "plano")
        self.b_deshacer.setShortcut("Ctrl+Z")
        self.ayuda = etiqueta("", "gris", True)
        self.b_sig = boton("Looks good, continue", self.siguiente, "primario")
        panel = tarjeta(self.foto_txt, self.heroe_rev, self.leyenda,
                        self.b_agregar, self.b_quitar, self.b_deshacer, self.ayuda)
        panel.layout().addStretch(1)
        panel.layout().addWidget(self.b_sig)
        panel.layout().addWidget(boton("Previous point", self.anterior, "plano"))
        panel.setFixedWidth(300)
        # Reproductor: el video corre y se detiene en cada punto de conteo
        self.cap, self.fps, self.cuadro, self.salto = None, 30.0, 0, 2
        self.cap_k, self.punto_de, self.rutas_video = None, {}, []
        self.desp, self.gris, self.hann, self.en_punto = [0.0, 0.0], None, None, True
        self.reloj_video = QtCore.QTimer(self)
        self.reloj_video.timeout.connect(self._tic)
        self.b_play = boton("Play", self.alternar_video)
        self.b_play.setFixedWidth(130)
        self.linea = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.linea.sliderReleased.connect(lambda: self.ir_a_cuadro(self.linea.value()))
        self.tiempo = etiqueta("", "gris")
        self.controles = QtWidgets.QWidget()
        lc = QtWidgets.QHBoxLayout(self.controles)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(14)
        lc.addWidget(self.b_play)
        lc.addWidget(self.linea, 1)
        lc.addWidget(self.tiempo)
        izq = QtWidgets.QVBoxLayout()
        izq.setSpacing(12)
        izq.addWidget(self.visor, 1)
        izq.addWidget(self.controles)
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(32, 14, 32, 28)
        lay.setSpacing(20)
        lay.addLayout(izq, 1)
        lay.addWidget(panel)
        self.pila.addWidget(w)

    def _a_revisar(self):
        self.poner_paso(1)
        self._abrir_video()
        primera = next((i for i, f in enumerate(self.fotos) if not f.revisada), 0)
        self.mostrar(primera)

    # ---- reproductor
    def _cerrar_video(self):
        self.reloj_video.stop()
        if self.cap is not None:
            self.cap.release()
        self.cap, self.cap_k, self.punto_de, self.rutas_video = None, None, {}, []

    def _ruta_video(self, v):
        for r in self.videos:
            if os.path.basename(r) == v["archivo"] and os.path.exists(r):
                return r
        return v["ruta"] if os.path.exists(v.get("ruta", "")) else None

    def _abrir_video(self):
        """Prepara los videos para verlos en Revisar. Sin video (carpeta de imagenes) se revisa imagen por imagen."""
        self._cerrar_video()
        vids, puntos = self.info.get("videos") or [], self.info.get("puntos") or []
        rutas = [self._ruta_video(v) for v in vids]
        nombres = {p["nombre"] for p in puntos}
        if vids and all(rutas) and all(f.nombre in nombres for f in self.fotos):
            self.rutas_video, self.punto_de = rutas, {p["nombre"]: p for p in puntos}
        self.controles.setVisible(bool(self.rutas_video))

    def _usar_video(self, k):
        """Deja abierto el video k (cuando un punto es de otro video que el que se estaba viendo)."""
        if self.cap_k == k and self.cap is not None:
            return
        if self.cap is not None:
            self.cap.release()
        self.cap, self.cap_k = cv2.VideoCapture(self.rutas_video[k]), k
        v = self.info["videos"][k]
        self.fps = float(v.get("fps") or 30.0)
        self.salto = max(1, int(round(self.fps / 15.0)))          # se muestran unas 15 imagenes por segundo
        self.linea.setRange(0, max(1, int(v.get("cuadros") or self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1)))
        self.reloj_video.setInterval(int(1000 * self.salto / self.fps))

    def _cuadro_de(self, i):
        """(video, cuadro) del punto i, o None sin video."""
        if not self.rutas_video or not 0 <= i < len(self.fotos):
            return None
        p = self.punto_de.get(self.fotos[i].nombre)
        return (p["video"], p["cuadro"]) if p else None

    def reproduciendo(self):
        return self.reloj_video.isActive()

    def alternar_video(self):
        self.pausar() if self.reproduciendo() else self.reproducir()

    def reproducir(self):
        if self.cap is None or not self.rutas_video or self.reproduciendo():
            return
        self.herramienta("mover")
        self.en_punto = False
        self.reloj_video.start()
        self._estado_video()

    def pausar(self):
        self.reloj_video.stop()
        self._estado_video()

    def _estado_video(self):
        corre = self.reproduciendo()
        self.b_play.setText("Pause" if corre else "Play")
        for b in (self.b_agregar, self.b_quitar):
            b.setEnabled(self.en_punto and not corre)        # solo se corrige con el video detenido en un punto
        self.b_sig.setEnabled(not corre)
        if self.cap is not None and self.rutas_video:
            seg, total = int(self.cuadro / self.fps), int(self.linea.maximum() / self.fps)
            cual = f"Video {self.cap_k + 1} of {len(self.rutas_video)} · " if len(self.rutas_video) > 1 else ""
            self.tiempo.setText(f"{cual}{seg // 60:02d}:{seg % 60:02d} / {total // 60:02d}:{total % 60:02d}")
            if not self.linea.isSliderDown():
                self.linea.setValue(self.cuadro)
            if not self.en_punto:
                sig = min(self.actual + 2, len(self.fotos))
                self.foto_txt.setText(f"Moving to point {sig} of {len(self.fotos)}…" if corre
                                      else f"Paused, before point {sig} of {len(self.fotos)}")
                self.b_sig.setText("Continue")

    def _tic(self):
        """Avanza el video. Los cuadros del ultimo punto se mueven con el suelo; al llegar al siguiente punto, se detiene."""
        sig = self.actual + 1
        destino = self._cuadro_de(sig)
        objetivo = destino[1] if destino and destino[0] == self.cap_k else None
        for _ in range(self.salto):
            if objetivo is not None and self.cuadro + 1 >= objetivo:
                self.reloj_video.stop()
                return self.mostrar(sig)
            if not self.cap.grab():                            # se acabo este video: sigue en el punto siguiente
                self.reloj_video.stop()
                return self.mostrar(sig) if sig < len(self.fotos) else self.pausar()
            self.cuadro += 1
        ok, img = self.cap.retrieve()
        if not ok or img is None:
            return self.pausar()
        self.visor.poner_cuadro(img)
        self._seguir(img)
        self._estado_video()

    def _chico(self, img):
        h, w = img.shape[:2]
        return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (320, max(8, int(round(320 * h / w))))).astype(np.float32)

    def _seguir(self, img):
        """Cuanto se movio el suelo desde el ultimo punto de conteo (correlacion de fase entre imagenes seguidas)."""
        h, w = img.shape[:2]
        chico = self._chico(img)
        if self.gris is not None and self.gris.shape == chico.shape:
            if self.hann is None or self.hann.shape != chico.shape:
                self.hann = cv2.createHanningWindow((chico.shape[1], chico.shape[0]), cv2.CV_32F)
            (dx, dy), _ = cv2.phaseCorrelate(self.gris, chico, self.hann)
            self.desp[0] += dx * w / chico.shape[1]
            self.desp[1] += dy * h / chico.shape[0]
        self.gris = chico
        lejos = abs(self.desp[0]) > 0.9 * w or abs(self.desp[1]) > 0.9 * h
        self.visor.desplazar_cajas(self.desp[0], self.desp[1], visibles=not lejos)

    def ir_a_cuadro(self, cuadro):
        """Arrastrar la linea de tiempo lleva al punto de conteo mas cercano."""
        if not self.rutas_video or not self.fotos:
            return
        del_video = [i for i in range(len(self.fotos)) if self._cuadro_de(i) and self._cuadro_de(i)[0] == self.cap_k]
        if del_video:
            self.mostrar(min(del_video, key=lambda i: abs(self._cuadro_de(i)[1] - cuadro)))

    def foto(self):
        return self.fotos[self.actual] if 0 <= self.actual < len(self.fotos) else None

    def mostrar(self, i):
        """Se detiene en el punto de conteo i: su imagen exacta, con los cuadros."""
        self.reloj_video.stop()
        self.actual = i
        f = self.foto()
        img = leer_imagen(f.ruta) if f else None
        self.visor.poner_foto(img)
        self.en_punto = True
        donde = self._cuadro_de(i) if f is not None else None
        if donde is not None:
            self._usar_video(donde[0])
            self.cuadro = donde[1]
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.cuadro + 1)       # el video sigue desde aqui
            self.desp, self.gris = [0.0, 0.0], (self._chico(img) if img is not None else None)
        self.herramienta("mover")
        self.refrescar2()
        self._estado_video()

    def refrescar2(self):
        f = self.foto()
        if not f:
            return
        v = f.visibles(CONF_DEFECTO)
        self.visor.poner_cajas(v, f.repetidas(CONF_DEFECTO))
        r = f.resumen(CONF_DEFECTO)
        self.foto_txt.setText(f"Count point {self.actual + 1} of {len(self.fotos)}" + ("  ·  reviewed" if f.revisada else ""))
        self.n_foto.setText(miles(r["total"]))
        self.llevas.setText(miles(sum(x.resumen(CONF_DEFECTO)["total"] for x in self.fotos[:self.actual + 1])))
        filas = [("Detected by the model", r["ia"]), ("Added by you", r["manual"]), ("Removed by you", r["quitadas"])]
        if r["repetidas"]:
            filas.append(("Already counted (dotted)", r["repetidas"]))
        html_f = "".join(f"<tr><td style='color:{GRIS}; padding:5px 0'>{k}</td>"
                         f"<td align='right' style='color:{TEXTO}; font-weight:600; padding:5px 0'>{miles(v)}</td></tr>" for k, v in filas)
        self.leyenda.setText(f"<table width='100%' cellspacing='0'>{html_f}</table>")
        self.leyenda.setToolTip("Cattle already counted at another point are shown dotted, with the number they got the "
                                "first time. They don't add up again." if r["repetidas"] else "")
        self.b_sig.setText("Looks good, see the result" if self.actual == len(self.fotos) - 1 else "Looks good, continue")
        self.b_deshacer.setEnabled(bool(self.deshacer_pila))

    def herramienta(self, cual):
        actual = self.visor.modo
        nuevo = "mover" if cual == actual else cual      # pulsar otra vez la suelta
        self.visor.poner_modo(nuevo)
        self.b_agregar.setChecked(nuevo == "agregar")
        self.b_quitar.setChecked(nuevo == "quitar")
        self.ayuda.setText({"agregar": "Click the missing animal, or drag to draw the box.",
                            "quitar": "Click the extra box.",
                            "mover": "Drag to move the image; the mouse wheel zooms in and out."}[nuevo])
        if nuevo != "mover" and self.reproduciendo():
            self.pausar()

    def agregar(self, x1, y1, x2, y2):
        f = self.foto()
        d = {"caja": [x1, y1, x2, y2], "conf": 1.0, "origen": "manual", "quitada": False}
        f.dets.append(d)
        self.deshacer_pila.append(("agregar", f, d))
        self._editado()

    def quitar(self, d):
        f = self.foto()
        if d["origen"] == "manual":
            f.dets = [x for x in f.dets if x is not d]
        else:
            d["quitada"] = True
        self.deshacer_pila.append(("quitar", f, d))
        self._editado()

    def deshacer(self):
        if not self.deshacer_pila:
            return
        accion, f, d = self.deshacer_pila.pop()
        if accion == "agregar":
            f.dets = [x for x in f.dets if x is not d]
        elif d["origen"] == "manual":
            f.dets.append(d)
        else:
            d["quitada"] = False
        if f is not self.foto():
            self.mostrar(self.fotos.index(f))
        self._editado()

    def _editado(self):
        self.numerar()                           # quitar o agregar una res cambia los numeros y las repetidas
        self.refrescar2()
        self.guardar_revision()

    def siguiente(self):
        if not self.en_punto:                    # en pausa a mitad de camino: solo sigue el video
            return self.reproducir()
        f = self.foto()
        f.revisada = True
        self.guardar_revision()
        if self.actual + 1 >= len(self.fotos):
            self._cerrar_video()
            self._a_reporte()
        elif self.cap is not None:
            self.reproducir()                    # el video corre hasta el siguiente punto y se detiene solo
        else:
            self.mostrar(self.actual + 1)

    def anterior(self):
        if self.actual > 0:
            self.mostrar(self.actual - 1)
        else:
            self._cerrar_video()
            self.poner_paso(0)

    # ---- paso 3
    def _paso3(self):
        p = Pagina(820)
        p.lay.setSpacing(24)
        self.r_cab = centrado(etiqueta("", "h2_sub", True))
        self.r_total = etiqueta("0", "heroe_numero")
        self.r_stats = [etiqueta("0", "numero_med") for _ in range(3)]
        # los tres datos en una sola tarjeta, cada uno centrado en su columna
        stats = Panel()
        stats.setObjectName("beneficios")
        ls = QtWidgets.QHBoxLayout(stats)
        ls.setContentsMargins(24, 24, 24, 26)
        ls.setSpacing(12)
        for k, (e, rot, ico) in enumerate(zip(self.r_stats, ("Detected by the model", "Added by you", "Removed by you"),
                                              ("modelo", "mas", "menos"))):
            if k:
                raya = QtWidgets.QFrame()
                raya.setObjectName("separador")
                ls.addWidget(raya)
            c = QtWidgets.QVBoxLayout()
            c.setSpacing(4)
            c.addWidget(insignia(ico, 44), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
            c.addSpacing(8)
            c.addWidget(centrado(e))
            c.addWidget(centrado(etiqueta(rot, "gris")))
            ls.addLayout(c, 1)
        # cuadre y hallazgos: un anuncio destacado, que solo aparece si hay algo que decir
        self.r_anuncio = brillo(Panel())
        self.r_anuncio.setObjectName("anuncio")
        self.r_hall = QtWidgets.QVBoxLayout(self.r_anuncio)
        self.r_hall.setContentsMargins(32, 26, 32, 28)
        self.r_hall.setSpacing(8)
        self.r_rev = centrado(etiqueta("", None, True))
        self.referencia = campo_numero(0)
        self.referencia.setSpecialValueText("Not counted")
        self.referencia.setFixedWidth(150)
        self.referencia.valueChanged.connect(lambda _: self._ref_txt())
        self.r_ref = etiqueta("", "gris", True)
        self.r_estado = etiqueta("", "gris", True)
        self.r_mapa = QtWidgets.QLabel()
        self.r_mapa.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.r_mapa_txt = centrado(etiqueta("Every animal counted, with its number, where it was seen.", "gris", True))
        self.r_union = QtWidgets.QVBoxLayout()
        self.ruta_mapa = None
        self.b_guardar = boton("Save and create PDF", self.elegir_pdf, "primario")
        cab = QtWidgets.QVBoxLayout()
        cab.setSpacing(6)
        cab.addWidget(centrado(etiqueta("Count report", "h2")))
        cab.addWidget(self.r_cab)
        p.lay.addLayout(cab)
        p.lay.addWidget(heroe(etiqueta("TOTAL CATTLE"), self.r_total, etiqueta("Each animal counted only once"), centro=True, icono_="res"))
        p.lay.addWidget(stats)
        p.lay.addWidget(self.r_anuncio)
        self.r_mapa_titulo = centrado(etiqueta("Count map", "h3"))
        self.r_mapa_ico = insignia("mapa", 44)
        p.lay.addWidget(tarjeta(fila(None, self.r_mapa_ico, None), self.r_mapa_titulo, self.r_mapa_txt, self.r_mapa, self.r_union,
                                self.r_rev, margen=28))
        p.lay.addWidget(tarjeta(
            fila(None, insignia("corral", 44), None),
            centrado(etiqueta("Corral count", "h3")),
            centrado(etiqueta("Did you count in the corral that same day? Enter it and AGI measures its own error.", "gris", True)),
            fila(None, self.referencia, self.r_ref, None), margen=28))
        firmado = QtWidgets.QLabel()
        firmado.setPixmap(icono("escudo", GRIS, 16))
        p.lay.addLayout(fila(None, firmado, etiqueta("The report is signed: nobody can change it without it showing.", "gris"), None, espacio=8))
        p.lay.addWidget(self.r_estado)
        p.lay.addLayout(fila(None, boton("Back to review", lambda: self._a_revisar()), self.b_guardar, None))
        p.lay.addStretch(1)
        self.pila.addWidget(p)

    def total(self):
        return reporte.resumen_total(self.fotos, CONF_DEFECTO)

    def cuadre_ahora(self):
        """El conteo que se va a guardar frente al anterior mas las ventas, compras y nacimientos anotados."""
        fid = self._finca_id()
        if fid is None:
            return None
        pot = self.potrero_elegido()
        return self.v.base.cuadre(fid, self.fecha.date().toString("yyyy-MM-dd"), self.total()["total"], [pot] if pot else None)

    def hallazgos_ahora(self):
        """Lo que se nota en este conteo antes de guardarlo: reses que faltan frente a las esperadas,
        o la caida frente al conteo anterior si no hay movimientos anotados."""
        return datos.hallazgos_de(self.cuadre_ahora(), CAIDA_ALERTA)

    def _a_reporte(self):
        t = self.total()
        pot = self.potrero_elegido()
        self.r_cab.setText(f"{self.finca.currentText().strip()}{' · ' + pot if pot else ''} · flight of "
                           f"{fecha_corta(self.fecha.date().toString('yyyy-MM-dd'))}")
        self.r_total.setText(miles(t["total"]))
        for e, k in zip(self.r_stats, ("ia", "manual", "quitadas")):
            e.setText(miles(t[k]))
        vaciar(self.r_hall)
        hall = self.hallazgos_ahora()
        q = self.cuadre_ahora()
        if q and q["movimientos"]:
            ok = abs(q["diferencia"]) < max(datos.MARGEN_CUADRE, round(q["esperadas"] * CAIDA_ALERTA / 100.0))
            self.r_hall.addWidget(insignia("cuadre", 44), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
            self.r_hall.addSpacing(6)
            self.r_hall.addWidget(centrado(etiqueta("Inventory reconciliation", "h3")))
            self.r_hall.addWidget(centrado(etiqueta(f"{texto_cuadre(q)} · AGI counted {miles(q['contadas'])}"
                                                    + ("  ✓ reconciled" if ok else f" ({q['diferencia']:+d})"), None, True)))
        if hall:
            if self.r_hall.count():
                self.r_hall.addSpacing(14)
            else:
                self.r_hall.addWidget(insignia("lupa", 44), 0, QtCore.Qt.AlignmentFlag.AlignHCenter)
                self.r_hall.addSpacing(6)
            self.r_hall.addWidget(centrado(etiqueta("Findings during the count", "h3")))
        for h in hall:
            self.r_hall.addWidget(centrado(etiqueta(texto_hallazgo(h)[0].upper() + texto_hallazgo(h)[1:] + ".", None, True)))
        self.r_anuncio.setVisible(self.r_hall.count() > 0)
        rev = sum(1 for f in self.fotos if f.revisada)
        self.r_rev.setText(f"✓  {rev} of {len(self.fotos)} images reviewed" if rev == len(self.fotos)
                           else f"Warning: only {rev} of {len(self.fotos)} images were reviewed. The report will say so.")
        rep = self.total().get("repetidas", 0)
        if rep:
            self.r_rev.setText(self.r_rev.text() + f"\n{rep} times an animal already counted showed up again at another point: it was counted only once.")
        self._mapa()
        self.r_estado.setText("")
        self._ref_txt()
        self.poner_paso(2)

    def _mapa(self):
        """Dibuja el mapa del conteo y avisa si una parte del vuelo no se pudo unir con el resto."""
        vaciar(self.r_union)
        self.ruta_mapa = None
        self.r_mapa.clear()
        hay = self.union is not None and bool(self.info.get("puntos"))
        self.r_mapa.setVisible(hay)
        self.r_mapa_txt.setVisible(hay)
        self.r_mapa_titulo.setVisible(hay)
        self.r_mapa_ico.setVisible(hay)
        if not hay:
            return
        rutas, dets = self._por_punto()
        try:
            img = vuelo.mapa_unico(rutas, self.union, dets, CONF_DEFECTO)
        except Exception as err:  # noqa: BLE001 - el mapa ayuda, pero no debe impedir el reporte
            self.r_mapa_txt.setText(f"Could not draw the map: {err}")
            return
        self.ruta_mapa = os.path.join(self.carpeta, "mapa_conteo.jpg")
        guardar_imagen(self.ruta_mapa, img)
        h, w = img.shape[:2]
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pm = QtGui.QPixmap.fromImage(QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888).copy())
        self.r_mapa.setPixmap(pm.scaled(640, 520, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                        QtCore.Qt.TransformationMode.SmoothTransformation))
        partes = self.union["grupos"]
        if partes > 1:
            self.r_union.addWidget(aviso(f"Part of the flight could not be joined to the rest (it ended up in {partes} parts). "
                                         "If an animal appears in two parts, it was counted twice: check the map."))

    def _ref_txt(self):
        ref = self.referencia.value()
        if not ref:
            self.r_ref.setText("")
            return
        dif = self.total()["total"] - ref
        self.r_ref.setText(f"AGI counted {dif:+d} ({100.0 * dif / ref:+.1f}%) versus the corral.")

    def elegir_pdf(self):
        pot = self.potrero_elegido()
        nombre = f"Count {self.finca.currentText().strip()}{' ' + pot if pot else ''} {self.fecha.date().toString('yyyy-MM-dd')}.pdf"
        ruta, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save report", os.path.join(self.carpeta, nombre), "PDF (*.pdf)")
        if ruta:
            self.guardar_reporte(ruta)

    def guardar_reporte(self, ruta):
        try:
            hall = [texto_hallazgo(h) for h in self.hallazgos_ahora()]
            conteo_id, codigo = reporte.generar(
                self.v.base, ruta, self.fotos, self.finca.currentText(), self.propietario.text().strip(),
                self.fecha.date().toString("yyyy-MM-dd"), CONF_DEFECTO, self.escala, self.v.modelo,
                hallazgos=hall, referencia=self.referencia.value() or None, origen=self.origen(), mapa=self.ruta_mapa,
                potrero=self.potrero_elegido(), cuadre=self.cuadre_ahora())
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.r_estado.setText(f"Could not save: {err}")
            return None
        self.guardar_revision()
        b = self.v.base
        fid = next(f[0] for f in b.fincas("") if f[1] == self.finca.currentText().strip() and f[2] == self.propietario.text().strip())
        self.v.abrir_finca(fid)
        self.v.statusBar().showMessage(f"Count saved and report signed. Code {codigo}.", 15000)
        return codigo

    def origen(self):
        vids = self.info.get("videos") or []
        if not vids:
            return None
        return {"videos": [v["archivo"] for v in vids], "duracion_s": round(sum(v["duracion_s"] for v in vids), 1),
                "puntos": len(self.info.get("puntos") or []), "partes": self.union["grupos"] if self.union else None}

    # ---- guardado de la revision (para retomar si se cierra)
    def guardar_revision(self):
        if not self.carpeta:
            return
        estado = {"finca": self.finca.currentText(), "propietario": self.propietario.text(),
                  "fecha_vuelo": self.fecha.date().toString("yyyy-MM-dd"), "escala": self.escala,
                  "fotos": {f.nombre: {"procesada": f.procesada, "revisada": f.revisada, "dets": f.dets} for f in self.fotos}}
        try:
            with open(os.path.join(self.carpeta, ARCHIVO_REVISION), "w", encoding="utf8") as fh:
                json.dump(estado, fh)
        except OSError:
            pass

    def _cargar_revision(self):
        ruta = os.path.join(self.carpeta, ARCHIVO_REVISION)
        if not os.path.exists(ruta):
            return
        try:
            with open(ruta, encoding="utf8") as fh:
                estado = json.load(fh)
        except (OSError, ValueError):
            return
        self.escala = estado.get("escala", 1.0)
        if not self.finca.currentText().strip():
            self.finca.setEditText(estado.get("finca", ""))
            self.propietario.setText(estado.get("propietario", ""))
        for f in self.fotos:
            g = estado.get("fotos", {}).get(f.nombre)
            if g:
                f.procesada, f.revisada, f.dets = g["procesada"], g["revisada"], g["dets"]


class PaginaAjustes(Pagina):
    def __init__(self, v):
        super().__init__()
        self.v = v
        self.lay.addWidget(etiqueta("Settings", "titulo"))
        self.tabs = QtWidgets.QTabWidget()
        self.lay.addWidget(self.tabs, 1)

    def refrescar(self, pestana=None):
        b, llave = self.v.base, self.v.llave
        actual = pestana if pestana is not None else (self.tabs.tabText(self.tabs.currentIndex()) if self.tabs.count() else "")
        self.tabs.clear()
        usuarios = DialogoUsuarios(b, llave)
        usuarios.setWindowFlags(QtCore.Qt.WindowType.Widget)
        self.tabs.addTab(usuarios, "Users")
        resp = DialogoRespaldo(b)
        resp.setWindowFlags(QtCore.Qt.WindowType.Widget)
        self.tabs.addTab(resp, "Backup")
        fid = b.finca_propia() if b.una_finca() else None
        if fid is not None:
            self.tabs.addTab(self._finca(fid), "Ranch")
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == actual:
                self.tabs.setCurrentIndex(i)

    def _finca(self, fid):
        f = self.v.base.datos_finca(fid)
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 16, 0, 0)
        lay.setSpacing(14)
        self.f_nombre, self.f_prop, self.f_motivo = QtWidgets.QLineEdit(f["nombre"]), QtWidgets.QLineEdit(f["propietario"]), QtWidgets.QLineEdit()
        self.f_motivo.setPlaceholderText("Why it changes (recorded in the audit log)")
        self.f_estado = etiqueta("", "gris", True)
        g = QtWidgets.QGridLayout()
        g.setHorizontalSpacing(14)
        g.setVerticalSpacing(6)
        for i, (rot, campo) in enumerate((("Ranch name", self.f_nombre), ("Owner", self.f_prop))):
            g.addWidget(etiqueta(rot, "campo"), 0, i)
            g.addWidget(campo, 1, i)
        self.s_estado = etiqueta("", "gris", True)
        avanzados = [boton("Verify the audit log", self.verificar), boton("Save the signing key…", self.guardar_llave_firma),
                     boton("Export data (CSV)…", self.exportar)]
        lay.addWidget(tarjeta(
            etiqueta("This account handles a single ranch", "destacado"),
            etiqueta("That way nobody saves a ranch's video under another ranch's name by mistake. Here you can only fix the "
                     "name or the owner; reports already signed keep the name they were signed with.",
                     "gris", True),
            g, etiqueta("Reason", "campo"), self.f_motivo, self.f_estado,
            fila(None, boton("Save change", self.renombrar, "primario")), margen=28))
        lay.addWidget(tarjeta(etiqueta("For reviews and audits", "seccion"),
                              etiqueta("Check that nobody changed the history, and export the key used to verify the "
                                       "signed reports.", "gris", True), fila(*avanzados, None), self.s_estado))
        lay.addStretch(1)
        self._fid_propia = fid
        return w

    def renombrar(self):
        try:
            self.v.base.renombrar_finca(self._fid_propia, self.f_nombre.text(), self.f_prop.text(), self.f_motivo.text())
        except Exception as err:  # noqa: BLE001 - se muestra al usuario
            self.f_estado.setText(str(err))
            return
        self.f_motivo.clear()
        self.f_estado.setText("Done. The change was recorded in the audit log.")

    def verificar(self):
        ok, n = self.v.base.verificar_bitacora()
        self.s_estado.setText(f"Audit log intact: {n} entries." if ok else f"WARNING: the audit log was altered near entry {n}.")

    def guardar_llave_firma(self):
        ruta, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save signing key", "llave_publica.pem", "PEM (*.pem)")
        if ruta:
            with open(ruta, "w", encoding="ascii") as fh:
                fh.write(self.v.base.llave_publica())
            self.s_estado.setText(f"Guardada. Huella: {seguridad.huella_llave(self.v.base.llave_publica())}")

    def exportar(self):
        r = QtWidgets.QMessageBox.warning(self, "Export data", "The CSV files are NOT encrypted: anyone who has them can see the "
                                          "inventory of every ranch. Export?",
                                          QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if r != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        carpeta = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the CSV files")
        if carpeta:
            self.v.base.exportar_csv(carpeta)
            self.s_estado.setText(f"Exportado a {carpeta}")


# ------------------------------------------------------------------ Ventana

class Ventana(QtWidgets.QMainWindow):
    def __init__(self, base, llave, modelo=MODELO):
        super().__init__()
        self.base, self.llave, self.modelo = base, llave, modelo
        cargar_fuentes()
        self.setWindowTitle("AGI · Cattle inventory")
        self.setWindowIcon(QtGui.QIcon(pixmap_marca(64)))
        self.resize(1280, 800)

        barra = QtWidgets.QFrame()
        barra.setObjectName("barra")
        self.b_fincas = boton("My ranch" if base.una_finca() else "Ranches", self.inicio, "nav", True)
        self.b_ajustes = boton("Settings", lambda: self.ir("ajustes"), "nav", True)
        self.b_ajustes.setVisible(base.rol == "admin")
        self.b_respaldo = boton("", lambda: self.ir("ajustes", "Backup") if base.rol == "admin" else DialogoRespaldo(base, self).exec(), "respaldo")
        self.b_respaldo.setIconSize(QtCore.QSize(14, 14))
        avatar = etiqueta(base.usuario[:1].upper(), "avatar")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lb = QtWidgets.QHBoxLayout(barra)
        lb.setContentsMargins(32, 12, 32, 12)
        lb.setSpacing(6)
        lb.addWidget(Marca(38))
        lb.addSpacing(22)
        lb.addWidget(self.b_fincas)
        lb.addWidget(self.b_ajustes)
        lb.addStretch(1)
        lb.addWidget(self.b_respaldo)
        lb.addSpacing(14)
        lb.addWidget(avatar)
        lb.addSpacing(4)
        lb.addWidget(etiqueta(base.usuario))

        # Pie: lo que el usuario necesita saber de sus datos, y la version
        pie = QtWidgets.QWidget()
        lp = QtWidgets.QHBoxLayout(pie)
        lp.setContentsMargins(4, 0, 0, 0)
        lp.setSpacing(8)
        candado = QtWidgets.QLabel()
        candado.setPixmap(icono("candado", GRIS, 14))
        lp.addWidget(candado)
        lp.addWidget(etiqueta("Data encrypted on this computer"))
        version = etiqueta(f"AGI {datos.VERSION}")
        version.setContentsMargins(0, 0, 24, 0)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setContentsMargins(22, 2, 0, 2)
        self.statusBar().addWidget(pie)
        self.statusBar().addPermanentWidget(version)

        self.p_fincas, self.p_finca = PaginaFincas(self), PaginaFinca(self)
        self.p_contar, self.p_ajustes = PaginaContar(self), PaginaAjustes(self)
        self.pila = QtWidgets.QStackedWidget()
        self.paginas = {"fincas": self.p_fincas, "finca": self.p_finca, "contar": self.p_contar,
                        "ajustes": self.p_ajustes}
        for p in self.paginas.values():
            self.pila.addWidget(p)
        raiz = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(raiz)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(barra)
        lay.addWidget(self.pila, 1)
        self.capas = QtWidgets.QStackedWidget()          # 0: la aplicacion, 1: sesion bloqueada
        self.capas.addWidget(raiz)
        self.capas.addWidget(self._pantalla_bloqueo())
        self.setCentralWidget(self.capas)
        self.inicio()

        # Si nadie toca el equipo en un rato, se bloquea y pide la contrasena otra vez
        self.reloj = QtCore.QTimer(self)
        self.reloj.setSingleShot(True)
        self.reloj.timeout.connect(self.bloquear)
        try:
            minutos = int(base.config("bloqueo_minutos", "10"))
        except ValueError:
            minutos = 10
        self.reloj.setInterval(max(0, minutos) * 60 * 1000)
        if minutos > 0:
            self.reloj.start()
            QtWidgets.QApplication.instance().installEventFilter(self)
        QtCore.QTimer.singleShot(0, self.avisar_integridad)

    # ---- bloqueo por inactividad
    def _pantalla_bloqueo(self):
        panel = Panel()
        panel.setObjectName("panel_marca")
        self.b_clave = QtWidgets.QLineEdit()
        self.b_clave.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.b_clave.setPlaceholderText("Password")
        self.b_clave.setMinimumHeight(46)
        self.b_clave.returnPressed.connect(self.desbloquear)
        self.b_error = etiqueta("", "error_oscuro", True)
        centro = QtWidgets.QWidget()
        centro.setFixedWidth(340)
        c = QtWidgets.QVBoxLayout(centro)
        c.setSpacing(12)
        c.addWidget(Marca(64))
        c.addSpacing(18)
        c.addWidget(etiqueta("Session locked", "lema"))
        c.addWidget(etiqueta(f"Nobody used AGI for a while. Enter {self.base.usuario}'s password to continue.", "lema_sub", True))
        c.addSpacing(8)
        c.addWidget(self.b_clave)
        c.addWidget(self.b_error)
        entrar = boton("Unlock", self.desbloquear, "primario")
        entrar.setMinimumHeight(48)
        c.addWidget(entrar)
        lay = QtWidgets.QGridLayout(panel)
        lay.addWidget(centro, 0, 0, QtCore.Qt.AlignmentFlag.AlignCenter)
        return panel

    def bloqueada(self):
        return self.capas.currentIndex() == 1

    def bloquear(self):
        if self.bloqueada():
            return
        self.base.anotar("sesion_bloqueada")
        self.b_clave.clear()
        self.b_error.setText("")
        self.capas.setCurrentIndex(1)
        self.b_clave.setFocus()

    def desbloquear(self):
        try:
            llave = seguridad.abrir_almacen(self.base.carpeta, self.base.usuario, self.b_clave.text())
            if not hmac.compare_digest(llave, self.base.llave):
                raise seguridad.ErrorAcceso("Wrong user or password.")
        except seguridad.ErrorAcceso as err:
            self.b_error.setText(str(err).replace("Wrong user or password", "Wrong password"))
            self.b_clave.clear()
            return
        fallos = seguridad.fallos_sin_avisar(self.base.carpeta)
        if fallos:
            self.base.anotar("intentos_fallidos", {"cuantos": fallos, "donde": "lock screen"})
        self.base.anotar("sesion_desbloqueada")
        self.b_clave.clear()
        self.capas.setCurrentIndex(0)
        self.reloj.start()

    def eventFilter(self, obj, ev):
        if ev.type() in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.MouseButtonPress, QtCore.QEvent.Type.MouseMove,
                         QtCore.QEvent.Type.Wheel) and not self.bloqueada() and self.reloj.interval() > 0:
            self.reloj.start()                     # hubo actividad: el reloj vuelve a empezar
        return False

    def avisar_integridad(self):
        """Al abrir: se revisa el archivo de la base y la bitacora, y se dice si algo no cuadra."""
        problemas = self.base.revisar_integridad()
        if problemas:
            QtWidgets.QMessageBox.warning(self, "Data check", "\n".join(problemas) + "\n\nDon't keep counting until it's checked.")
        return problemas

    # ---- navegacion
    def ir(self, donde, pestana=None):
        self.statusBar().clearMessage()
        if donde == "fincas":
            self.p_fincas.refrescar()
        elif donde == "ajustes":
            self.p_ajustes.refrescar(pestana)
        self.pila.setCurrentWidget(self.paginas[donde])
        self.b_fincas.setChecked(donde in ("fincas", "finca", "contar"))
        self.b_ajustes.setChecked(donde == "ajustes")
        self.refrescar_barra()

    def refrescar_barra(self):
        dias = self.base.dias_sin_respaldo()
        if not self.base.config("carpeta_respaldo") or dias is None:
            texto, al_dia = "No backup", False
        else:
            texto = "Backup: " + ("today" if dias < 1 else ("yesterday" if dias < 2 else f"{int(dias)} days ago"))
            al_dia = dias < 7
        self.b_respaldo.setText(texto)
        self.b_respaldo.setIcon(QtGui.QIcon(icono("check", ACENTO, 14)) if al_dia else QtGui.QIcon())

    def refrescar_todo(self):
        self.p_fincas.refrescar()
        self.refrescar_barra()

    def inicio(self):
        """La pantalla de entrada: en una cuenta de una sola finca, la finca misma; si no, la lista."""
        fid = self.base.finca_propia() if self.base.una_finca() else None
        if fid is not None:
            self.abrir_finca(fid)
        else:
            self.ir("fincas")

    def abrir_finca(self, finca_id):
        self.p_finca.abrir(finca_id)
        self.ir("finca")

    def nuevo_conteo(self, finca_id=None):
        self.p_contar.empezar(finca_id)
        self.ir("contar")

    # ---- cierre
    def respaldo_al_cerrar(self):
        if (self.base.config("respaldo_al_cerrar", "1") != "1" or not self.base.config("carpeta_respaldo")
                or not self.base.hay_cambios_sin_respaldar()):
            return None
        return self.base.respaldar()

    def closeEvent(self, ev):
        if self.p_contar.hilo is not None:
            self.p_contar.hilo.cancelar = True
            self.p_contar.hilo.wait(5000)
        self.p_contar._cerrar_video()
        self.p_contar.guardar_revision()
        try:
            self.respaldo_al_cerrar()
        except Exception as err:  # noqa: BLE001 - p. ej. la USB no esta puesta
            r = QtWidgets.QMessageBox.warning(self, "Could not back up", f"The backup could not be made ({err}).\nClose anyway?",
                                              QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if r != QtWidgets.QMessageBox.StandardButton.Yes:
                ev.ignore()
                return
        QtWidgets.QApplication.instance().removeEventFilter(self)
        self.reloj.stop()
        self.base.cerrar()
        super().closeEvent(ev)


def autoprueba(ruta_salida):
    """AGI.exe --autoprueba archivo.txt: comprueba que el programa empacado trae todo lo que necesita
    (modelo, fuentes, base cifrada, PDF, Excel, video) sin abrir ventanas. Lo usa el armado en GitHub."""
    import tempfile
    lineas, ok = [], True

    def paso(nombre, f):
        nonlocal ok
        try:
            extra = f()
            lineas.append(f"ok    {nombre}" + (f": {extra}" if extra else ""))
        except Exception as err:  # noqa: BLE001 - se reporta todo
            ok = False
            lineas.append(f"FAIL  {nombre}: {type(err).__name__}: {err}")

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])     # no abre ninguna ventana
    paso("version", lambda: datos.VERSION)

    def modelo_integro():
        problema = comprobar_modelo(MODELO)
        if problema:
            raise RuntimeError(problema)
        return os.path.basename(MODELO)
    paso("counting model intact", modelo_integro)
    paso("model loads in onnxruntime", lambda: contar.cargar_modelo(MODELO).get_providers()[0])
    paso("Manrope fonts", lambda: cargar_fuentes() or "loaded")

    def sello():
        if pixmap_marca(64).isNull():
            raise RuntimeError("no image")
    paso("AGI seal", sello)
    tmp = tempfile.mkdtemp(prefix="agi_autoprueba_")

    def base_cifrada():
        b, _, _ = crear_sesion(os.path.join(tmp, "datos"), "revisor", "llano-verde-58-sol")
        cifrada = b.cifrada
        b.cerrar()
        if not cifrada:
            raise RuntimeError("the database was not encrypted")
        return "SQLCipher"
    paso("encrypted database", base_cifrada)

    def pdf():
        ruta = os.path.join(tmp, "p.pdf")
        w = QtGui.QPdfWriter(ruta)
        p = QtGui.QPainter(w)
        p.drawText(100, 100, "AGI")
        p.end()
        return f"{os.path.getsize(ruta)} bytes"
    paso("PDF", pdf)
    paso("Excel", lambda: __import__("openpyxl").__version__)

    def video():
        ruta = os.path.join(tmp, "v.mp4")
        w = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
        for _ in range(5):
            w.write(np.zeros((48, 64, 3), np.uint8))
        w.release()
        cap = cv2.VideoCapture(ruta)
        leidos = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        if leidos < 1:
            raise RuntimeError("OpenCV can't read video")
        return f"{leidos} frames"
    paso("video (OpenCV)", video)
    lineas.append("RESULT: " + ("ALL GOOD" if ok else "FAILURES"))
    with open(ruta_salida, "w", encoding="utf8") as fh:
        fh.write("\n".join(lineas) + "\n")
    del app
    return 0 if ok else 1


def main():
    if "--autoprueba" in sys.argv:
        i = sys.argv.index("--autoprueba")
        sys.exit(autoprueba(sys.argv[i + 1] if len(sys.argv) > i + 1 else "agi_autoprueba.txt"))
    if sys.platform == "win32":
        try:                    # que la barra de tareas muestre el sello de AGI y no el icono de Python
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AGI.InventarioGanadero")
        except Exception:  # noqa: BLE001 - solo cosmetico
            pass
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("AGI")
    app.setApplicationDisplayName("AGI")
    aplicar_tema(app)
    app.setWindowIcon(QtGui.QIcon(pixmap_marca(256)))
    candado = tomar_candado(carpeta_datos())
    if candado is None:
        QtWidgets.QMessageBox.information(None, "AGI", "AGI is already open on this computer.")
        sys.exit(0)
    instalar_registro_errores(carpeta_datos())
    while True:
        acceso = DialogoAcceso(carpeta_datos())
        r = acceso.exec()
        if r == DialogoAcceso.RESTAURADO:
            continue                        # ya hay datos: ahora pide usuario y contrasena
        if r != QtWidgets.QDialog.DialogCode.Accepted:
            sys.exit(0)
        break
    v = Ventana(acceso.base, acceso.llave)
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
