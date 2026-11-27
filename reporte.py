"""Reporte PDF firmado de un conteo. Guarda el conteo en la base y escribe el PDF
con su archivo de firma. Lo usa agi.py; no depende de la ventana."""
import datetime
import json
import os
import tempfile

import cv2
from PySide6 import QtCore, QtGui

import contar
import datos
import seguridad
import piezas
from piezas import CAJA_IA, CAJA_MANUAL, guardar_imagen, leer_imagen

# El PDF es un documento para imprimir: papel blanco, tinta negra y grises neutros. No sigue el tema de la aplicacion.
TINTA, GRIS, FONDO, LINEA, CLARO = "#0A0A0A", "#5C5C5C", "#F5F5F5", "#E5E5E5", "#D9D9D9"
ACENTO, FILETE = "#FFFFFF", "#6B9BE1"      # numero destacado sobre las cajas negras; filete azul pizarra bajo la franja


def resumen_total(fotos, umbral):
    t = {"total": 0, "ia": 0, "manual": 0, "quitadas": 0, "repetidas": 0}
    for f in fotos:
        for k, v in f.resumen(umbral).items():
            t[k] += v
    return t


def generar(base, ruta, fotos, finca, propietario, fecha_vuelo, umbral, escala, modelo="", hallazgos=(), referencia=None, origen=None,
            mapa=None, potrero="", cuadre=None):
    """fecha_vuelo: 'AAAA-MM-DD'. hallazgos: textos que el programa noto en este conteo.
    referencia: conteo en corral del mismo dia, si lo hay. origen: de que videos salieron las imagenes
    ({"videos", "duracion_s", "puntos", "partes"}). mapa: ruta del mapa del conteo. potrero: '' si el vuelo
    cubrio toda la finca. cuadre: el de Base.cuadre para este conteo, si lo hay. Devuelve (conteo_id, codigo)."""
    t = resumen_total(fotos, umbral)
    finca = finca.strip()
    if not finca:
        raise ValueError("The ranch name is missing.")
    ahora = datetime.datetime.now()
    hoy = f"{MESES[ahora.month - 1][:3]} {ahora.day}, {ahora.year}, {ahora:%H:%M}"
    sin = [f.nombre for f in fotos if not f.revisada]

    # 1) guardar en la base: el manifiesto firmado lleva la huella de cada foto
    finca_id = base.finca(finca, propietario)
    fotos_m = [dict(f.resumen(umbral), nombre=f.nombre, sha256=seguridad.sha256_archivo(f.ruta), revisada=f.revisada,
                    cajas=[[round(c, 1) for c in d["caja"]] + [d["origen"], d.get("id")] for d in f.visibles(umbral)],
                    repetidas=[[round(c, 1) for c in d["caja"]] + [d.get("id")] for d in f.repetidas(umbral)]) for f in fotos]
    extra = {"modelo_sha256": seguridad.sha256_archivo(modelo) if modelo and os.path.exists(modelo) else "",
             "hallazgos": list(hallazgos)}
    if referencia:
        extra["conteo_en_corral"] = int(referencia)
    if origen:
        extra["origen"] = dict(origen)
    if cuadre and cuadre.get("movimientos"):
        extra["cuadre"] = {k: cuadre[k] for k in ("fecha_base", "base", "entradas", "salidas", "esperadas", "diferencia")}
    if mapa and os.path.exists(mapa):
        extra["mapa_sha256"] = seguridad.sha256_archivo(mapa)
    conteo_id, codigo, manifiesto, _ = base.guardar_conteo(finca_id, fecha_vuelo, t, fotos_m, umbral, escala, extra=extra,
                                                           potrero=potrero)
    if referencia:
        base.poner_referencia(conteo_id, referencia)
    publica = base.llave_publica()

    # 2) el PDF, con la identidad de AGI: franja negra con el logo, filete azul pizarra, Manrope en titulos
    fecha_txt = _fecha(fecha_vuelo)
    lugar = f"{finca} · {potrero}" if potrero else finca
    pdf = _Pdf(ruta, lugar, fecha_txt, codigo)
    pdf.portada(lugar, propietario, fecha_txt, t, len(fotos), sin, (origen or {}).get("partes") or 1, hallazgos, referencia)
    if cuadre and cuadre.get("movimientos"):
        pdf.titulo("Inventory reconciliation")
        pdf.cuadre(cuadre)
    pdf.titulo("Count details")
    datos_f = [("Ranch", finca)] + ([("Paddock", potrero)] if potrero else []) + [
               ("Owner", propietario or "—"), ("Flight date", fecha_txt),
               ("Reviewed by", base.usuario), ("Issued", hoy)]
    if origen:
        seg = int(origen.get("duracion_s") or 0)
        vids = origen.get("videos") or []
        datos_f += [("Video" if len(vids) == 1 else "Videos", ", ".join(vids)),
                    ("Duration", f"{seg // 60} min {seg % 60:02d} s"), ("Count points", _miles(origen.get("puntos") or len(fotos)))]
    else:
        datos_f.append(("Images counted", _miles(len(fotos))))
    pdf.datos(datos_f)
    pdf.titulo("Count points")
    pdf.tabla(["Count point", "New", "Already counted", "Model", "Added", "Removed", "Reviewed"],
              [[f.nombre] + [_miles(f.resumen(umbral)[k]) for k in ("total", "repetidas", "ia", "manual", "quitadas")]
               + ["Yes" if f.revisada else "No"] for f in fotos],
              [0.37, 0.10, 0.12, 0.10, 0.11, 0.10, 0.10])
    pdf.cabe(48)
    pdf.titulo("How to read this report")
    pdf.leyenda()
    pdf.parrafo("AGI takes a count point every time the drone advances half a frame and places all the points on a "
                "single plane by matching the images against each other. Each animal gets a number the first time it is seen; if "
                "it shows up again at another point it keeps that number and is not added again. The total is the number of "
                "distinct numbers. If an animal moved a lot between one pass and the next, it may be counted twice.")
    pdf.titulo("Digital signature")
    pdf.firma(codigo, seguridad.huella_llave(publica), os.path.basename(ruta) + ".firma.json")
    with tempfile.TemporaryDirectory() as tmp:
        if mapa and os.path.exists(mapa):
            pdf.pagina_imagen("Count map",
                              "Each animal counted appears only once, with its number, where it was seen. The white "
                              "lines mark what each count point could see; the dark areas were not seen.", [], mapa)
        for k, f in enumerate(fotos):
            r = f.resumen(umbral)
            img = leer_imagen(f.ruta)
            if img is None:
                continue
            v = f.visibles(umbral)
            esc = min(1.0, 1800.0 / max(img.shape[:2]))      # imagen liviana para el PDF
            if esc < 1.0:
                img = cv2.resize(img, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
            cajas = [[c * esc for c in d["caja"]] for d in v]
            colores = [CAJA_MANUAL[::-1] if d["origen"] == "manual" else CAJA_IA[::-1] for d in v]
            ids = [d.get("id", k2) for k2, d in enumerate(v, 1)]
            punteadas = [[c * esc for c in d["caja"]] for d in f.repetidas(umbral)]
            p = os.path.join(tmp, f"foto_{k}.jpg")
            guardar_imagen(p, contar.dibujar(img, cajas, None, colores, ids, punteadas))
            fichas = [("New", _miles(r["total"]), True), ("Already counted", _miles(r["repetidas"]), False),
                      ("Model", _miles(r["ia"]), False), ("Added", _miles(r["manual"]), False),
                      ("Removed", _miles(r["quitadas"]), False),
                      ("Review", "Reviewed" if f.revisada else "Not reviewed", not f.revisada and "alerta")]
            pdf.pagina_imagen(f"Point {k + 1} of {len(fotos)}", f.nombre, fichas, p)
        pdf.cerrar()

    # 3) archivo de firma junto al PDF
    huella_pdf = seguridad.sha256_archivo(ruta)
    sobre = {"manifiesto": manifiesto, "pdf_sha256": huella_pdf, "llave_publica": publica,
             "firma": base.firmar(seguridad.canonico({"manifiesto": manifiesto, "pdf_sha256": huella_pdf}))}
    with open(ruta + ".firma.json", "w", encoding="utf8") as fh:
        json.dump(sobre, fh, ensure_ascii=False, indent=1)
    base.registrar_pdf(conteo_id, huella_pdf, ruta)
    return conteo_id, codigo


# ---------------------------------------------------------------- diseno del PDF

MESES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
         "November", "December")
ROJO, ROJO_FONDO = "#9B1C1C", "#FBEAEA"
AVISO, AVISO_FONDO = "#2B4A7F", "#EAF0FA"       # hallazgos: azul pizarra, como los avisos de la aplicacion
VERDE, VERDE_FONDO = "#1E6B3A", "#E7F3EA"
COLOR_IA, COLOR_MANUAL = "#%02X%02X%02X" % CAJA_IA, "#%02X%02X%02X" % CAJA_MANUAL     # los mismos de los recuadros
LETRA = ["Segoe UI", "Inter", "Helvetica", "Arial"]


def _fecha(iso):
    d = datetime.date.fromisoformat(iso)
    return f"{MESES[d.month - 1]} {d.day}, {d.year}"


def _miles(n):
    return f"{int(n):,}"


def _c(hexa):
    return QtGui.QColor(hexa)


class _Pdf:
    """Dibuja el reporte pagina por pagina con QPainter. Todas las medidas van en milimetros."""
    RES = 300
    MARGEN, BANDA, PIE = 16.0, 17.0, 14.0

    def __init__(self, ruta, finca, fecha_txt, codigo):
        piezas.cargar_fuentes()
        self.w = QtGui.QPdfWriter(ruta)
        self.w.setPageSize(QtGui.QPageSize(QtGui.QPageSize.PageSizeId.A4))
        self.w.setPageMargins(QtCore.QMarginsF(0, 0, 0, 0))
        self.w.setResolution(self.RES)
        self.w.setTitle(f"Count report · {finca} · {fecha_txt}")
        self.w.setCreator("AGI")
        self.k = self.RES / 25.4
        self.ancho, self.alto = self.w.width() / self.k, self.w.height() / self.k
        self.finca, self.fecha_txt, self.codigo = finca, fecha_txt, codigo
        self.p = QtGui.QPainter(self.w)
        self.p.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
                              | QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        self.n = 0
        self._pagina()

    # -- utilidades
    def r(self, x, y, w, h):
        return QtCore.QRectF(x * self.k, y * self.k, w * self.k, h * self.k)

    def letra(self, pt, peso="normal", titulos=False):
        f = QtGui.QFont()
        if titulos:
            f.setFamilies(["Manrope SemiBold" if peso == "semi" else "Manrope"] + LETRA)
            f.setWeight(QtGui.QFont.Weight.Bold if peso != "semi" else QtGui.QFont.Weight.Normal)
        else:
            f.setFamilies(LETRA)
            f.setWeight({"normal": QtGui.QFont.Weight.Normal, "semi": QtGui.QFont.Weight.DemiBold,
                         "bold": QtGui.QFont.Weight.Bold}[peso])
        f.setPointSizeF(pt)
        return f

    def escribir(self, x, y, w, h, texto, pt, color=TINTA, peso="normal", titulos=False,
                 alinear=QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, espaciado=0, cortar=False):
        f = self.letra(pt, peso, titulos)
        if espaciado:
            f.setLetterSpacing(QtGui.QFont.SpacingType.PercentageSpacing, 100 + espaciado)
        self.p.setFont(f)
        self.p.setPen(_c(color))
        if cortar:
            texto = QtGui.QFontMetricsF(f, self.w).elidedText(texto, QtCore.Qt.TextElideMode.ElideMiddle, w * self.k)
        self.p.drawText(self.r(x, y, w, h), int(alinear), texto)

    def caja(self, x, y, w, h, fondo, borde=None, radio=2.2):
        self.p.setPen(QtGui.QPen(_c(borde), 0.25 * self.k) if borde else QtCore.Qt.PenStyle.NoPen)
        self.p.setBrush(_c(fondo) if fondo else QtCore.Qt.BrushStyle.NoBrush)
        self.p.drawRoundedRect(self.r(x, y, w, h), radio * self.k, radio * self.k)

    def linea(self, x1, y1, x2, y2, color=LINEA, grosor=0.25):
        self.p.setPen(QtGui.QPen(_c(color), grosor * self.k))
        self.p.drawLine(QtCore.QPointF(x1 * self.k, y1 * self.k), QtCore.QPointF(x2 * self.k, y2 * self.k))

    @property
    def util(self):
        return self.ancho - 2 * self.MARGEN

    def cabe(self, h):
        if self.y + h > self.alto - self.PIE - 6:
            self._pagina()

    # -- pagina: franja con el sello arriba y pie con el codigo
    def _pagina(self):
        if self.n:
            self.w.newPage()
        self.n += 1
        m, b = self.MARGEN, self.BANDA
        self.p.fillRect(self.r(0, 0, self.ancho, b), _c(TINTA))
        self.p.fillRect(self.r(0, b, self.ancho, 0.8), _c(FILETE))
        lado = 11.0
        img = piezas._imagen_sello(int(lado * self.k))
        if img is not None:
            self.p.drawImage(self.r(m, (b - lado) / 2, lado, lado), img)
        self.escribir(m + lado + 3, 0, 30, b, "AGI", 15, "#FFFFFF", titulos=True, espaciado=12)
        self.escribir(m + lado + 17, 0, 80, b, "Cattle count report", 9, CLARO)
        self.escribir(self.ancho - m - 90, 0, 90, b, f"{self.finca}  ·  {self.fecha_txt}", 9, CLARO,
                      alinear=QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter, cortar=True)
        yp = self.alto - self.PIE
        self.linea(m, yp, self.ancho - m, yp)
        self.escribir(m, yp, 120, self.PIE, f"Verification code  {self.codigo}   ·   Report digitally signed by AGI",
                      7.5, GRIS)
        self.escribir(self.ancho - m - 40, yp, 40, self.PIE, f"Page {self.n}", 7.5, GRIS,
                      alinear=QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter)
        self.y = b + 11

    # -- bloques
    def titulo(self, texto):
        self.cabe(22)
        self.y += 4
        self.p.fillRect(self.r(self.MARGEN, self.y + 1.6, 1.2, 5), _c(TINTA))
        self.escribir(self.MARGEN + 4, self.y, self.util, 8, texto, 12.5, titulos=True)
        self.y += 11

    def parrafo(self, texto, color=GRIS, pt=9, ancho=None, x=None, mover=True):
        x = self.MARGEN if x is None else x
        ancho = ancho or self.util
        doc = QtGui.QTextDocument()
        doc.documentLayout().setPaintDevice(self.w)
        doc.setDefaultFont(self.letra(pt))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color:{color}; line-height:140%'>{texto}</div>")
        doc.setTextWidth(ancho * self.k)
        h = doc.size().height() / self.k
        if mover:
            self.cabe(h)
        self.p.save()
        self.p.translate(x * self.k, self.y * self.k)
        doc.drawContents(self.p)
        self.p.restore()
        if mover:
            self.y += h + 4
        return h

    def aviso(self, texto, tipo):
        color, fondo = {"rojo": (ROJO, ROJO_FONDO), "ambar": (AVISO, AVISO_FONDO), "verde": (VERDE, VERDE_FONDO)}[tipo]
        doc_h = self._alto_texto(texto, self.util - 14, 9)
        h = doc_h + 7
        self.cabe(h)
        self.caja(self.MARGEN, self.y, self.util, h, fondo)
        self.p.fillRect(self.r(self.MARGEN, self.y, 1.2, h), _c(color))
        y0 = self.y
        self.y += 3.5
        self.parrafo(texto, color, 9, self.util - 14, self.MARGEN + 7, mover=False)
        self.y = y0 + h + 3

    def _alto_texto(self, texto, ancho, pt):
        doc = QtGui.QTextDocument()
        doc.documentLayout().setPaintDevice(self.w)
        doc.setDefaultFont(self.letra(pt))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='line-height:140%'>{texto}</div>")
        doc.setTextWidth(ancho * self.k)
        return doc.size().height() / self.k

    def portada(self, finca, propietario, fecha_txt, t, n_fotos, sin, partes, hallazgos, referencia):
        m = self.MARGEN
        self.escribir(m, self.y, self.util, 5, "COUNT REPORT", 8, GRIS, "semi", espaciado=14)
        self.y += 6
        self.escribir(m, self.y, self.util, 13, finca, 24, titulos=True, cortar=True)
        self.y += 13
        sub = " · ".join(x for x in (propietario, f"Flight of {fecha_txt}") if x)
        self.escribir(m, self.y, self.util, 6, sub, 10.5, GRIS)
        self.y += 12
        # tarjeta del total
        h, wt = 46.0, 70.0
        self.caja(m, self.y, wt, h, TINTA, radio=3)
        self.escribir(m + 7, self.y + 6, wt - 14, 5, "TOTAL CATTLE", 8, CLARO, "semi", espaciado=14)
        self.escribir(m + 6, self.y + 12, wt - 12, 22, _miles(t["total"]), 44, ACENTO, titulos=True)
        self.escribir(m + 7, self.y + 35, wt - 14, 5, "each animal counted only once", 8, CLARO)
        # fichas al lado
        x0, gap = m + wt + 5, 4.0
        wf = (self.util - wt - 5 - gap) / 2
        hf = (h - gap) / 2
        fichas = [("Detected by the model", t["ia"]), ("Added in review", t["manual"]),
                  ("Removed in review", t["quitadas"]), ("Seen again (not added)", t["repetidas"])]
        for i, (lbl, val) in enumerate(fichas):
            x = x0 + (i % 2) * (wf + gap)
            y = self.y + (i // 2) * (hf + gap)
            self.caja(x, y, wf, hf, FONDO, LINEA)
            self.escribir(x + 5, y + 3.5, wf - 10, 5, lbl, 8, GRIS)
            self.escribir(x + 5, y + 9, wf - 10, 10, _miles(val), 18, titulos=True)
        self.y += h + 6
        if sin:
            self.aviso(f"<b>Warning:</b> {len(sin)} of {n_fotos} images were not marked as reviewed by a person.",
                       "rojo")
        else:
            self.aviso("<b>Reviewed:</b> every image was reviewed by a person before signing.", "verde")
        if partes > 1:
            self.aviso(f"<b>Warning:</b> part of the flight could not be joined to the rest (it ended up in {partes} parts). "
                       "If an animal appeared in two parts, it was counted twice.", "rojo")
        if referencia:
            dif = t["total"] - int(referencia)
            err = 100.0 * dif / int(referencia)
            self.aviso(f"<b>Corral count the same day:</b> {_miles(referencia)} cattle. AGI difference: "
                       f"{dif:+d} ({err:+.1f}%).", "ambar")
        for hh in hallazgos:
            self.aviso(f"<b>Finding:</b> {_esc(hh)}", "ambar")

    def datos(self, filas):
        m, fila = self.MARGEN, 8.2
        col = self.util / 2
        n = (len(filas) + 1) // 2
        self.cabe(n * fila + 4)
        for i, (k, v) in enumerate(filas):
            x = m + (i // n) * col
            y = self.y + (i % n) * fila
            self.linea(x, y + fila, x + col - 6, y + fila)
            self.escribir(x, y, 30, fila, k, 8.5, GRIS)
            self.escribir(x + 30, y, col - 36, fila, str(v), 9, TINTA, "semi", cortar=True)
        self.y += n * fila + 6

    def tabla(self, cabeza, filas, prop):
        m, fila = self.MARGEN, 7.6
        anchos = [p * self.util for p in prop]

        def encabezado():
            self.caja(m, self.y, self.util, fila, FONDO, radio=1.5)
            x = m
            for i, (c, w) in enumerate(zip(cabeza, anchos)):
                al = QtCore.Qt.AlignmentFlag.AlignLeft if i == 0 else QtCore.Qt.AlignmentFlag.AlignRight
                self.escribir(x + 2, self.y, w - 4, fila, c, 7.5, GRIS, "semi",
                              alinear=al | QtCore.Qt.AlignmentFlag.AlignVCenter)
                x += w
            self.y += fila

        self.cabe(fila * 3)
        encabezado()
        for f in filas:
            if self.y + fila > self.alto - self.PIE - 6:
                self._pagina()
                encabezado()
            x = m
            for i, (c, w) in enumerate(zip(f, anchos)):
                al = QtCore.Qt.AlignmentFlag.AlignLeft if i == 0 else QtCore.Qt.AlignmentFlag.AlignRight
                color, peso = TINTA, "normal"
                if i == 1:
                    peso = "bold"
                if i == len(f) - 1:
                    color, peso = (VERDE, "semi") if c == "Yes" else (ROJO, "semi")
                if i in (2, 3, 4, 5) and c == "0":
                    color = "#A6A6A6"
                self.escribir(x + 3, self.y, w - 6, fila, c, 8.5, color, peso,
                              alinear=al | QtCore.Qt.AlignmentFlag.AlignVCenter, cortar=(i == 0))
                x += w
            self.linea(m, self.y + fila, m + self.util, self.y + fila)
            self.y += fila
        self.y += 6

    def cuadre(self, q):
        """Conteo anterior + entradas - salidas = esperadas, frente a las contadas."""
        m, h = self.MARGEN, 26.0
        self.cabe(h + 12)
        d = datetime.date.fromisoformat(q["fecha_base"])
        piezas_c = [(f"Count of {MESES[d.month - 1][:3]} {d.day}", _miles(q["base"]), None),
                    ("Came in", f"+{_miles(q['entradas'])}", None), ("Went out", f"−{_miles(q['salidas'])}", None),
                    ("Expected", _miles(q["esperadas"]), None), ("AGI counted", _miles(q["contadas"]), True)]
        gap = 3.0
        w = (self.util - gap * (len(piezas_c) - 1)) / len(piezas_c)
        for i, (lbl, val, marca) in enumerate(piezas_c):
            x = m + i * (w + gap)
            self.caja(x, self.y, w, h, TINTA if marca else FONDO, None if marca else LINEA)
            self.escribir(x + 4, self.y + 4, w - 8, 5, lbl, 7.5, CLARO if marca else GRIS, cortar=True)
            self.escribir(x + 4, self.y + 11, w - 8, 10, val, 17, ACENTO if marca else TINTA, titulos=True)
        self.y += h + 4
        margen = max(datos.MARGEN_CUADRE, round(q["esperadas"] * 0.05))
        dif = q["diferencia"]
        if abs(dif) < margen:
            self.aviso(f"<b>Reconciled.</b> The difference ({dif:+d}) is within the count's margin of error.", "verde")
        elif dif < 0:
            self.aviso(f"<b>{_miles(-dif)} cattle missing without explanation.</b> Check whether a sale, a death "
                       "or a transfer is missing from the log; if not, it is worth riding the ranch.", "rojo")
        else:
            self.aviso(f"<b>{_miles(dif)} more cattle than expected.</b> A birth or a purchase may be missing from the log.",
                       "ambar")
        nombres = datos.PLURAL_MOVIMIENTO
        if q.get("detalle"):
            self.parrafo("Movements logged between the two counts: "
                         + ", ".join(f"{_miles(n)} {nombres.get(k, k)}" for k, n in q["detalle"].items()) + ".", GRIS, 8.5)

    def leyenda(self):
        m, h = self.MARGEN, 8.0
        self.cabe(h + 4)
        items = [("Counted by AGI", "solida", COLOR_IA), ("Added in review", "solida", COLOR_MANUAL),
                 ("Already counted at another point", "punteada", "#8C8C8C")]
        x = m
        for txt, tipo, color in items:
            pen = QtGui.QPen(_c(color), 0.6 * self.k)
            if tipo == "punteada":
                pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            self.p.setPen(pen)
            self.p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            self.p.drawRect(self.r(x, self.y + 1.8, 6, 4.4))
            self.escribir(x + 8.5, self.y, 50, h, txt, 8.5, TINTA)
            x += 58
        self.y += h + 3

    def firma(self, codigo, huella, archivo):
        m = self.MARGEN
        texto = (f"This report comes with the file <i>{_esc(archivo)}</i>. With that file and the issuer's public "
                 "issuer, anyone can check that neither the PDF nor the figures changed after it was issued, and that the "
                 "images are the ones that were counted. The signature doesn't prove where or when the video was recorded.")
        h = max(30.0, self._alto_texto(texto, self.util - 100, 8) + 10)
        self.cabe(h + 4)
        self.caja(m, self.y, self.util, h, FONDO, LINEA, radio=3)
        self.escribir(m + 7, self.y + 4, 60, 5, "VERIFICATION CODE", 7.5, GRIS, "semi", espaciado=12)
        self.escribir(m + 7, self.y + 10, 80, 10, codigo, 17, titulos=True, espaciado=6)
        self.escribir(m + 7, self.y + 21, 80, 5, f"Issuer key  {huella}", 8, GRIS)
        y0 = self.y
        self.y += 5
        self.parrafo(texto, GRIS, 8, self.util - 100, m + 93, mover=False)
        self.y = y0 + h + 4

    def pagina_imagen(self, titulo, sub, fichas, ruta_img):
        self._pagina()
        m = self.MARGEN
        self.escribir(m, self.y, self.util, 9, titulo, 15, titulos=True)
        self.y += 9
        self.escribir(m, self.y, self.util, 5, sub, 8.5, GRIS, cortar=True) if len(sub) < 90 else None
        if len(sub) >= 90:
            self.parrafo(sub, GRIS, 8.5)
        else:
            self.y += 8
        if fichas:
            gap = 3.0
            wf = (self.util - gap * (len(fichas) - 1)) / len(fichas)
            for i, (lbl, val, marca) in enumerate(fichas):
                x = m + i * (wf + gap)
                fondo, borde, color = (FONDO, LINEA, TINTA)
                if marca is True:
                    fondo, borde, color = TINTA, None, ACENTO
                elif marca == "alerta":
                    fondo, borde, color = ROJO_FONDO, None, ROJO
                self.caja(x, self.y, wf, 15, fondo, borde)
                self.escribir(x + 3.5, self.y + 2, wf - 7, 5, lbl, 7, CLARO if marca is True else GRIS)
                self.escribir(x + 3.5, self.y + 6.5, wf - 7, 7, val, 12 if len(val) < 6 else 9.5, color, titulos=True)
            self.y += 21
        img = QtGui.QImage(ruta_img)
        if img.isNull():
            return
        disp_w, disp_h = self.util, self.alto - self.PIE - 8 - self.y
        esc = min(disp_w / img.width(), disp_h / img.height())
        w, h = img.width() * esc, img.height() * esc
        x = m + (self.util - w) / 2
        ruta = QtGui.QPainterPath()
        ruta.addRoundedRect(self.r(x, self.y, w, h), 2.2 * self.k, 2.2 * self.k)
        self.p.save()
        self.p.setClipPath(ruta)
        self.p.drawImage(self.r(x, self.y, w, h), img)
        self.p.restore()
        self.p.setPen(QtGui.QPen(_c(LINEA), 0.3 * self.k))
        self.p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        self.p.drawPath(ruta)
        self.y += h + 4

    def cerrar(self):
        self.p.end()
        del self.p
        del self.w


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
