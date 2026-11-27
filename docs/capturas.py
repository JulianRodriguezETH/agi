"""Rehace las capturas de docs/img y el reporte de ejemplo de ejemplos_app/ con el tema actual de la aplicacion.

  python docs/capturas.py . salida/        (deja todo en salida/; de ahi se copia a docs/img y ejemplos_app)

Usa un vuelo simulado hecho con una foto de ejemplos/ y datos de mentira en una carpeta temporal.
Necesita lo mismo que la aplicacion y, para la captura del PDF, pdftoppm (poppler).
"""
import sys, os, time, shutil, tempfile, subprocess
R, SAL = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
TESELA = (sys.argv[3], int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else ("mosaico_3.jpg", 0, 1)
sys.path.insert(0, R); os.makedirs(SAL, exist_ok=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import cv2, numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import agi as G, piezas as P, datos
qa = QtWidgets.QApplication([]); G.aplicar_tema(qa)
for n in ("information", "warning", "critical"):
    setattr(QtWidgets.QMessageBox, n, staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Ok))
QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
def girar(ms):
    t0 = time.time()
    while time.time() - t0 < ms / 1000: qa.processEvents(); time.sleep(0.01)
def foto(w, nombre):
    girar(120); w.grab().save(os.path.join(SAL, nombre)); print("captura", nombre, w.size().width(), w.size().height())
raiz = tempfile.mkdtemp(prefix="capturas_")
d = os.path.join(raiz, "datos")

# 01 crear cuenta
acc = P.DialogoAcceso(d); acc.resize(1280, 800); acc.show(); girar(50)
acc.usuario.setText("rancher"); acc.clave.setText("llanura-verde-27-sol"); acc.clave2.setText("llanura-verde-27-sol")
foto(acc, "01_crear_cuenta.png"); acc.close()

base, llave, _ = P.crear_sesion(d, "rancher", "llanura-verde-27-sol")
fid = base.finca("Example Ranch A", "Example Owner")
base.guardar_conteo(fid, "2026-10-20", {"total": 44, "ia": 44, "manual": 0, "quitadas": 0}, [])
base.anotar_movimiento(fid, "2026-11-05", "venta", 14, "Livestock fair")
base.anotar_movimiento(fid, "2026-11-10", "nacimiento", 2)
usb = tempfile.mkdtemp(prefix="USB_AGI_", dir="/dev/shm")     # otro disco: asi no sale el aviso de "mismo disco"
base.poner_carpeta_respaldo(usb)

# vuelo simulado: una foto aerea de ejemplos/ ampliada, el dron baja 560 px en 14 s
nombre, fy, fx = TESELA
g = cv2.imread(os.path.join(R, "ejemplos", nombre))
t = cv2.resize(g[fy*640:(fy+1)*640, fx*640:(fx+1)*640], (1280, 1280), interpolation=cv2.INTER_CUBIC)
video = os.path.join(raiz, "DJI_20261122_0001.mp4")
w = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (1280, 720))
for y in range(0, 561, 4): w.write(np.ascontiguousarray(t[y:y+720]))
w.release()

base.respaldar()
v = G.Ventana(base, llave); v.resize(1280, 800); v.show(); girar(100)
v.nuevo_conteo(); c = v.p_contar
c.fecha.setDate(QtCore.QDate(2026, 11, 22))
c.poner_videos([video])
t0 = time.time()
while c.extractor is not None and time.time() - t0 < 240: qa.processEvents(); time.sleep(0.02)
girar(100); print("puntos:", len(c.fotos), c.fotos_txt.text())
foto(v, "00_video.png")
c.contar(); t0 = time.time()
while (c.hilo is not None or c.pila.currentIndex() == 0) and time.time() - t0 < 300: qa.processEvents(); time.sleep(0.02)
girar(300); foto(v, "04_revisar.png")
c.siguiente(); t0 = time.time(); girar(300)
while c.reproduciendo() and time.time() - t0 < 90: qa.processEvents(); time.sleep(0.01)
girar(300); foto(v, "05_ya_contadas.png")
for _ in range(len(c.fotos)):
    if c.pila.currentIndex() == 2: break
    c.siguiente(); t0 = time.time(); girar(200)
    while c.reproduciendo() and time.time() - t0 < 90: qa.processEvents(); time.sleep(0.01)
girar(300); print("total:", c.total()); foto(v, "06_reporte.png")
EJ = os.path.join(SAL, "ejemplos_app"); os.makedirs(EJ, exist_ok=True)
pdf = os.path.join(EJ, "reporte_ejemplo.pdf")
print("codigo:", c.guardar_reporte(pdf))
base.respaldar(); v.refrescar_barra(); v.statusBar().clearMessage(); girar(300); foto(v, "02_finca.png")
pf = v.p_finca; sb = pf.verticalScrollBar(); sb.setValue(sb.maximum()); print("scroll max", sb.maximum())
foto(v, "03_cuadre.png"); sb.setValue(0)

# pantallas extra (ajustes, bloqueo): para revisar el tema en todas las interfaces
for pest in ("Users", "Backup", "Ranch"):
    v.ir("ajustes", pest); foto(v, f"x_ajustes_{pest.lower()}.png")
v.bloquear(); foto(v, "x_bloqueo.png"); v.b_clave.setText("llanura-verde-27-sol"); v.desbloquear(); v.ir("fincas"); girar(100)

# 07 anotar movimiento
dm = G.DialogoMovimiento(v, "Example Ranch A"); dm.show(); girar(50)
dm.tipo.setCurrentIndex(dm.tipo.findData("muerte")); dm.cantidad.setValue(1); dm.fecha.setDate(QtCore.QDate(2026, 11, 25))
dm.nota.setText("Lightning in the upper paddock")
foto(dm, "07_movimiento.png"); dm.close()

# 08 respaldo
base.respaldar()
dr = P.DialogoRespaldo(base, v); dr.show(); girar(50)
dr.carpeta.setText("/media/USB_AGI")
foto(dr, "08_respaldo.png"); dr.close()

# 09 pdf (primera pagina)
subprocess.run(["pdftoppm", "-png", "-r", "100", "-f", "1", "-l", "1", pdf, os.path.join(SAL, "09_pdf")], check=True)
for f in os.listdir(SAL):
    if f.startswith("09_pdf-"): os.replace(os.path.join(SAL, f), os.path.join(SAL, "09_pdf.png"))
with open(os.path.join(EJ, "llave_publica.pem"), "w", encoding="ascii") as fh: fh.write(base.llave_publica())
v.close(); base.cerrar()

# ---- reporte de ejemplo (ejemplos_app/) y mapa: el vuelo en dos lineas de probar_app.py sobre ejemplos/mosaico_1.jpg
grande = cv2.resize(P.leer_imagen(os.path.join(R, "ejemplos", "mosaico_1.jpg")), (1920, 1920))
def grabar(ruta, cuadros):
    w = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (1280, 720))
    for c_ in cuadros: w.write(np.ascontiguousarray(c_))
    w.release(); return ruta
va = grabar(os.path.join(raiz, "line_a.mp4"), [grande[y:y + 720, 0:1280] for y in range(0, 1201, 6)])
vb = grabar(os.path.join(raiz, "line_b.mp4"), [cv2.rotate(grande[y:y + 720, 640:1920], cv2.ROTATE_180) for y in range(1200, -1, -6)])
d2 = os.path.join(raiz, "datos2")
b2, l2, _ = P.crear_sesion(d2, "rancher", "llanura-verde-27-sol")
b2.finca("Example Ranch A", "Example Owner")
v2 = G.Ventana(b2, l2); v2.resize(1280, 800); v2.show(); girar(100)
v2.nuevo_conteo(); c = v2.p_contar
c.fecha.setDate(QtCore.QDate(2026, 11, 22)); c.poner_videos([va, vb])
t0 = time.time()
while c.extractor is not None and time.time() - t0 < 240: qa.processEvents(); time.sleep(0.02)
girar(100); c.contar(); t0 = time.time()
while (c.hilo is not None or c.pila.currentIndex() == 0) and time.time() - t0 < 300: qa.processEvents(); time.sleep(0.02)
for _ in range(len(c.fotos) + 2):
    if c.pila.currentIndex() == 2: break
    c.siguiente(); t0 = time.time(); girar(200)
    while c.reproduciendo() and time.time() - t0 < 120: qa.processEvents(); time.sleep(0.01)
girar(300); print("ejemplo: puntos", len(c.fotos), "revisadas", sum(1 for f in c.fotos if f.revisada), "total", c.total())
shutil.copy2(os.path.join(c.carpeta, "mapa_conteo.jpg"), os.path.join(EJ, "mapa_conteo.jpg"))
shutil.copy2(os.path.join(c.carpeta, "mapa_conteo.jpg"), os.path.join(SAL, "10_mapa.jpg"))
print(sorted(os.listdir(EJ)))
v2.close(); b2.cerrar()
acc2 = P.DialogoAcceso(d); acc2.resize(1280, 800); acc2.show(); girar(50); acc2.usuario.setText("rancher"); foto(acc2, "x_entrar.png"); acc2.close()
shutil.rmtree(raiz, ignore_errors=True); shutil.rmtree(usb, ignore_errors=True)
print("LISTO")
