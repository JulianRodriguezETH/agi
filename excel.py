"""Exporta el inventario a un libro de Excel (.xlsx): resumen, conteos, movimientos, cuadres y meses.
El archivo sale SIN cifrar: queda anotado en la bitacora. Necesita openpyxl."""
import datetime

TINTA, LINEA, GRIS = "0A0A0A", "E5E5E5", "5C5C5C"
MESES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fecha(iso):
    return datetime.date.fromisoformat(iso[:10]) if iso else None


def exportar(base, ruta, finca_id=None):
    """finca_id=None: todas las fincas de esta instalacion."""
    from openpyxl import Workbook

    base._exigir("admin")
    fincas = [f for f in base.fincas() if finca_id is None or f[0] == finca_id]
    if not fincas:
        raise ValueError("No ranches to export.")
    libro = Workbook()
    hoja = lambda *a, **k: _hoja(libro, *a, **k)

    resumen, conteos, movs, cuadres, meses = [], [], [], [], []
    for fid, nombre, propietario, municipio, cliente in fincas:
        hist = base.historial(fid)
        esp = base.esperadas_hoy(fid)
        ult = hist[-1] if hist else None
        resumen.append([nombre, propietario, ult[1] if ult else None, _fecha(ult[0]) if ult else None,
                        ult[2] if ult else None, esp[0] if esp else None, len(hist)])
        for c in reversed(base.conteos_de(fid)):
            conteos.append([nombre, c["potrero"] or "Whole ranch", _fecha(c["fecha_vuelo"]), c["total"],
                            c["referencia"], c["usuario"], c["codigo"]])
        for m in reversed(base.movimientos(fid)):
            movs.append([nombre, _fecha(m["fecha"]), m["nombre"], m["signo"] * m["cantidad"], m["nota"], m["usuario"]])
        for h in hist:
            q = base.cuadre(fid, h[0], h[1], h[6])
            if q:
                cuadres.append([nombre, ", ".join(h[6]) or "Whole ranch", _fecha(q["fecha_base"]), q["base"],
                                q["entradas"], q["salidas"], q["esperadas"], _fecha(h[0]), q["contadas"], q["diferencia"]])
        for mes, total in base.por_mes(fid, 36):
            a, m = mes.split("-")
            meses.append([nombre, f"{MESES[int(m) - 1]} {a}", total])

    hoja("Summary", ["Ranch", "Owner", "Last count", "Date", "Change", "Expected today", "Counts"],
         resumen, [28, 24, 15, 13, 11, 15, 10], fechas=(3,), numeros=(2, 4, 5, 6), primera=True)
    hoja("Counts", ["Ranch", "Paddock", "Flight date", "Cattle", "Corral count", "Counted by", "Code"],
         conteos, [28, 18, 16, 10, 11, 16, 18], fechas=(2,), numeros=(3, 4))
    hoja("Movements", ["Ranch", "Date", "Movement", "Cattle (+ in, − out)", "Note", "Logged by"],
         movs, [28, 13, 22, 22, 36, 16], fechas=(1,), numeros=(3,))
    hoja("Reconciliation", ["Ranch", "Paddock", "Previous count", "Cattle then", "Came in", "Went out", "Expected",
                    "Count", "Counted", "Difference"],
         cuadres, [28, 18, 16, 15, 11, 11, 12, 13, 11, 12], fechas=(2, 7), numeros=(3, 4, 5, 6, 8, 9))
    hoja("By month", ["Ranch", "Month", "Cattle at close"], meses, [28, 12, 16], numeros=(2,))
    libro.properties.creator = "AGI"
    libro.properties.title = "Cattle inventory"
    libro.save(ruta)
    base.anotar("excel_exportado", {"archivo": ruta.replace("\\", "/").rsplit("/", 1)[-1],
                                    "fincas": len(fincas)})
    return ruta



def _hoja(libro, titulo, columnas, filas, anchos, fechas=(), numeros=(), primera=False):
    """Una hoja con encabezado oscuro, filas con raya fina, fechas y numeros con formato, filtro y panel fijo."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    h = libro.active if primera else libro.create_sheet()
    h.title = titulo
    h.append(columnas)
    for c in h[1]:
        c.fill = PatternFill("solid", fgColor=TINTA)
        c.font = Font(bold=True, color="FFFFFF", name="Calibri", size=11)
        c.alignment = Alignment(vertical="center", horizontal="left", indent=1)
    h.row_dimensions[1].height = 26
    for f in filas:
        h.append(f)
    raya = Border(bottom=Side(style="thin", color=LINEA))
    for fila in h.iter_rows(min_row=2):
        for c in fila:
            c.border = raya
            col = c.column - 1
            if col in fechas and c.value:
                c.number_format = "yyyy-mm-dd"
            elif col in numeros:
                c.number_format = "#,##0;-#,##0;0"
    for i, w in enumerate(anchos, 1):
        h.column_dimensions[get_column_letter(i)].width = w
    h.freeze_panes = "A2"
    if filas:
        h.auto_filter.ref = h.dimensions
    h.sheet_view.showGridLines = False
    return h

