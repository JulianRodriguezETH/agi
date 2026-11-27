"""Prueba la aplicacion sin pantalla: bloqueo de sesion, una sola ventana, registro de
errores, cambio de llave desde el panel, fotos danadas, modelo cambiado y revision al abrir.

  set QT_QPA_PLATFORM=offscreen
  python probar_app.py

Usa las fotos de ejemplos/ y una carpeta temporal que borra al terminar.
"""
import sys, os, time, json, shutil, tempfile
AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
raiz = tempfile.mkdtemp(prefix="prueba_app_")
FOTOS = sys.argv[1] if len(sys.argv) > 1 else os.path.join(AQUI, "ejemplos")
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
import agi as G, piezas as P, datos, seguridad
qa = QtWidgets.QApplication([]); G.aplicar_tema(qa)
mens = []
for n in ("information", "warning", "critical"):
    setattr(QtWidgets.QMessageBox, n, staticmethod(lambda *a, **k: mens.append(a[2]) or QtWidgets.QMessageBox.StandardButton.Ok))
QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.StandardButton.Yes)
FALLOS = []
def comprobar(nombre, ok, detalle=""):
    print(("  ok   " if ok else "  FALLA ") + nombre + (f"  [{detalle}]" if detalle and not ok else ""))
    if not ok: FALLOS.append(nombre)
def girar(ms):
    t0 = time.time()
    while time.time() - t0 < ms / 1000: qa.processEvents(); time.sleep(0.01)
d = os.path.join(raiz, "datos"); sal = os.path.join(raiz, "sal"); os.makedirs(sal, exist_ok=True)

print("Una sola ventana y registro de errores")
c1 = P.tomar_candado(d); comprobar("la primera ventana toma el candado", c1 is not None)
comprobar("una segunda ventana sobre los mismos datos no abre", P.tomar_candado(d) is None)
c1.unlock(); c2 = P.tomar_candado(d); comprobar("al cerrar la primera, ya se puede abrir", c2 is not None); c2.unlock()
ruta = P.instalar_registro_errores(d)
try: 1 / 0
except ZeroDivisionError: sys.excepthook(*sys.exc_info())
comprobar("un error inesperado queda en agi_errores.log y se avisa", "ZeroDivisionError" in open(ruta, encoding="utf8").read() and "agi_errores.log" in mens[-1])
sys.excepthook = sys.__excepthook__

print("Bloqueo de sesión")
base, llave, _ = P.crear_sesion(d, "ana", "clave-larga-de-prueba")
v = G.Ventana(base, llave); v.show(); girar(50)
comprobar("base nueva: la revisión al abrir no avisa nada", not [m for m in mens if "bitácora" in m.lower()])
v.bloquear(); girar(30); v.grab().save(os.path.join(sal, "agi_bloqueada.png"))
comprobar("bloqueada: la aplicación queda tapada", v.bloqueada() and not v.pila.isVisible())
v.b_clave.setText("no-es-la-clave"); v.desbloquear()
comprobar("contraseña mala: sigue bloqueada y lo dice", v.bloqueada() and "wrong" in v.b_error.text().lower(), v.b_error.text())
v.b_clave.setText("clave-larga-de-prueba"); v.desbloquear()
acc = [x[3] for x in base.bitacora()]
comprobar("contraseña buena: desbloquea y queda todo en la bitácora", not v.bloqueada() and {"sesion_bloqueada", "sesion_desbloqueada", "intentos_fallidos"} <= set(acc), str(acc[:5]))
comprobar("por defecto se bloquea a los 10 minutos sin uso", v.reloj.interval() == 600000 and v.reloj.isActive())
v.reloj.setInterval(400); v.reloj.start(); girar(250); QTest.keyClick(v, QtCore.Qt.Key.Key_Shift); girar(250)
comprobar("si hay actividad, el reloj vuelve a empezar", not v.bloqueada())
girar(500); comprobar("sin actividad, se bloquea sola", v.bloqueada())
v.b_clave.setText("clave-larga-de-prueba"); v.desbloquear(); v.reloj.setInterval(600000); v.reloj.start()

print("Desactivar a alguien cambia la llave")
base.crear_usuario(llave, "operador1", "sombrero-azul-41", "operador")
antes = base.llave; v.ir("ajustes", "Usuarios")
panel = v.p_ajustes.findChild(P.DialogoUsuarios)
fila = [i for i in range(panel.tabla.rowCount()) if panel.tabla.item(i, 0).text() == "operador1"][0]
panel.tabla.setCurrentCell(fila, 0); panel.desactivar(); girar(30)
comprobar("desde el panel: la llave cambia y lo dice", base.llave != antes and "key" in panel.estado.text(), panel.estado.text())
base.crear_usuario(llave, "operador2", "tractor-amarillo-63", "operador")       # 'llave' es la vieja: no debe importar
comprobar("un usuario creado después entra con la llave nueva", seguridad.abrir_almacen(d, "operador2", "tractor-amarillo-63") == base.llave)

print("Fotos dañadas y modelo cambiado")
vuelo = os.path.join(raiz, "vuelo"); os.makedirs(vuelo, exist_ok=True)
buenas = sorted(f for f in os.listdir(FOTOS) if f.lower().endswith(".jpg") and not f.lower().endswith("_conteo.jpg"))[:2]
for f in buenas: shutil.copy2(os.path.join(FOTOS, f), os.path.join(vuelo, f))
open(os.path.join(vuelo, "DJI_9999.JPG"), "wb").write(b"esto no es una foto" * 50)
def contar_en(ventana):
    ventana.nuevo_conteo(); c = ventana.p_contar
    c.finca.setEditText("Finca de ejemplo A"); c.propietario.setText("Propietario de ejemplo"); c.poner_carpeta(vuelo); c.contar()
    t0 = time.time()
    while c.hilo is not None and time.time() - t0 < 120: qa.processEvents(); time.sleep(0.02)
    girar(50); return c
c = contar_en(v)
comprobar("la foto dañada queda fuera y se avisa con su nombre", len(c.fotos) == 2 and "DJI_9999.JPG" in mens[-1] and c.pila.currentIndex() == 1, f"{len(c.fotos)} {mens[-1][:60]}")
comprobar("…y queda en la bitácora", "fotos_ilegibles" in [x[3] for x in base.bitacora()])
mod = os.path.join(raiz, "modelo"); os.makedirs(mod, exist_ok=True)
shutil.copy2(P.MODELO, os.path.join(mod, "reses_s.onnx")); shutil.copy2(P.MODELO + ".sha256", os.path.join(mod, "reses_s.onnx.sha256"))
comprobar("el modelo original pasa la comprobación", P.comprobar_modelo(P.MODELO) is None and P.comprobar_modelo(os.path.join(mod, "reses_s.onnx")) is None)
with open(os.path.join(mod, "reses_s.onnx"), "ab") as fh: fh.write(b"x")
os.remove(os.path.join(vuelo, P.ARCHIVO_REVISION)) if os.path.exists(os.path.join(vuelo, P.ARCHIVO_REVISION)) else None
v.modelo = os.path.join(mod, "reses_s.onnx"); c = contar_en(v)
comprobar("con el modelo cambiado AGI se niega a contar", "not the original" in c.estado1.text() and c.pila.currentIndex() == 0, c.estado1.text())
v.modelo = P.MODELO; v.ir("fincas"); v.close()

print("Videos del vuelo: sin contar dos veces la misma res")
import cv2, numpy as np, contar, vuelo
# vuelo simulado en dos lineas sobre una foto grande (1920 x 1920): la A baja por la izquierda; la B sube por la
# derecha con el dron girado 180 grados. Las lineas se traslapan 640 px.
grande = cv2.resize(P.leer_imagen(os.path.join(FOTOS, buenas[0])), (1920, 1920))
def grabar(ruta, cuadros):
    w = cv2.VideoWriter(ruta, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (1280, 720))
    for c_ in cuadros: w.write(np.ascontiguousarray(c_))
    w.release()
    return ruta
va = grabar(os.path.join(raiz, "linea_a.mp4"), [grande[y:y + 720, 0:1280] for y in range(0, 1201, 6)])
vb = grabar(os.path.join(raiz, "linea_b.mp4"), [cv2.rotate(grande[y:y + 720, 640:1920], cv2.ROTATE_180) for y in range(1200, -1, -6)])
todas = sorted(f for f in os.listdir(FOTOS) if f.lower().endswith(".jpg") and not f.lower().endswith("_conteo.jpg"))
otra = cv2.resize(P.leer_imagen(os.path.join(FOTOS, todas[-1])), (1920, 1920))      # otro potrero (mosaico_1 y _2 comparten una foto)
vc = grabar(os.path.join(raiz, "otro_potrero.mp4"), [otra[y:y + 720, 0:1280] for y in range(0, 601, 6)])
ref = int((contar.detectar(contar.cargar_modelo(P.MODELO), grande, conf=P.CONF_MIN)[1] >= G.CONF_DEFECTO).sum())

# numeros fijos, con dos puntos inventados: el segundo esta 150 px a la derecha del primero
caja = lambda cx, cy, origen="ia": {"caja": [cx - 20, cy - 15, cx + 20, cy + 15], "conf": 0.9, "origen": origen, "quitada": False}
antes, ahora = [caja(300, 200), caja(900, 500)], [caja(150, 200), caja(750, 500), caja(1200, 400), caja(600, 800), caja(151, 201, "manual")]
puntos_ = [{"seguido": False, "mov": None, "video": 0}, {"seguido": True, "mov": [-150, 0], "video": 0}]
union_ = {"G": [np.eye(3), np.array([[1, 0, 150], [0, 1, 0], [0, 0, 1.0]])], "grupo": [0, 0], "rel": {}, "tam": [[1280, 960]] * 2}
total_ = vuelo.numerar([antes, ahora], union_, 0.3, puntos_)
comprobar("números fijos: la res repetida conserva el número de la original y no suma",
          total_ == 5 and [d["repetida"] for d in ahora] == [True, True, False, False, False]
          and ahora[0]["id"] == antes[0]["id"] and ahora[1]["id"] == antes[1]["id"], f"{total_} {[(d['repetida'], d.get('id')) for d in ahora]}")
comprobar("números fijos: lo agregado a mano nunca se marca repetido", not ahora[4]["repetida"] and ahora[4]["id"] not in (antes[0]["id"], antes[1]["id"]))

b3, l3 = P.abrir_sesion(d, "ana", "clave-larga-de-prueba")
v3 = G.Ventana(b3, l3); v3.show(); v3.nuevo_conteo(); c = v3.p_contar
c.finca.setEditText("Finca de ejemplo A"); c.poner_videos([va, vb])
comprobar("mientras lee los videos no se puede contar", not c.b_contar.isEnabled())
def esperar_lectura():
    t0 = time.time()
    while c.extractor is not None and time.time() - t0 < 240: qa.processEvents(); time.sleep(0.02)
    girar(50)
esperar_lectura()
pts = c.info.get("puntos") or []
comprobar("saca un punto cada vez que el dron avanza media imagen: 5 por línea", len(c.fotos) == 10 and "2 videos · 10 count points" in c.fotos_txt.text(),
          f"{len(c.fotos)} · {c.fotos_txt.text()} · cuadros {[p['cuadro'] for p in pts]}")
comprobar("une las dos líneas en un solo mapa, aunque la segunda va girada", c.union is not None and c.union["grupos"] == 1, str(c.union and c.union["grupos"]))
v3.grab().save(os.path.join(sal, "agi_video.png"))
if len(sys.argv) > 3: shutil.copy2(os.path.join(sal, "agi_video.png"), sys.argv[3])
c.contar(); t0 = time.time()
while (c.hilo is not None or c.pila.currentIndex() == 0) and time.time() - t0 < 300: qa.processEvents(); time.sleep(0.02)
comprobar("cuenta en todos los puntos y pasa a revisar", c.pila.currentIndex() == 1 and all(f.procesada for f in c.fotos), str(c.pila.currentIndex()))
comprobar("los videos cargados quedan en la bitácora", "video_cargado" in [x[3] for x in b3.bitacora()])
tot = c.total()
comprobar("sin quitar repetidas, la suma de los puntos sería mucho mayor que las reses que hay", tot["total"] + tot["repetidas"] > 1.5 * ref,
          f"suma {tot['total'] + tot['repetidas']} ref {ref}")
comprobar("con números fijos el total queda cerca del conteo de todo el potrero de una vez", abs(tot["total"] - ref) <= max(3, 0.12 * ref),
          f"AGI {tot['total']} frente a {ref}")
print(f"       reses en el potrero completo: {ref} · suma de los 10 puntos: {tot['total'] + tot['repetidas']} · AGI: {tot['total']}")
cuentan = [dd for f in c.fotos for dd in f.dets if vuelo._cuenta(dd, G.CONF_DEFECTO)]
orig = [dd["id"] for dd in cuentan if not dd["repetida"]]
comprobar("cada res contada tiene un número propio y cada repetida apunta a una que existe",
          all("id" in dd for dd in cuentan) and len(orig) == len(set(orig)) == tot["total"]
          and all(dd["id"] in set(orig) for dd in cuentan if dd["repetida"]))

def hasta_que_pare(maximo=60):
    t0 = time.time()
    while c.reproduciendo() and time.time() - t0 < maximo: qa.processEvents(); time.sleep(0.01)
    girar(30)
comprobar("Revisar abre el reproductor, detenido en el primer punto", c.cap is not None and c.controles.isVisible() and c.actual == 0 and c.en_punto and not c.reproduciendo())
c.siguiente(); girar(1500)
comprobar("«Está bien, seguir» pone a correr el video", c.reproduciendo() and 5 <= c.cuadro < 60 and not c.b_agregar.isEnabled(), str(c.cuadro))
esperado = -6.0 * c.cuadro
comprobar("los cuadros se mueven con el suelo (6 px por cuadro hacia arriba)", abs(c.desp[1] - esperado) < 0.15 * abs(esperado) + 4 and abs(c.desp[0]) < 6,
          f"{c.desp[1]:.1f} esperado {esperado:.1f}, horizontal {c.desp[0]:.1f}")
hasta_que_pare()
sig_cuadro = pts[1]["cuadro"]
v3.grab().save(os.path.join(sal, "agi_reproductor.png"))
if len(sys.argv) > 4: shutil.copy2(os.path.join(sal, "agi_reproductor.png"), sys.argv[4])
comprobar("se detiene solo en el segundo punto, en su cuadro exacto", c.actual == 1 and c.cuadro == sig_cuadro and c.en_punto and c.fotos[0].revisada,
          f"{c.actual} {c.cuadro} esperado {sig_cuadro}")
comprobar("las reses ya contadas se ven punteadas y con su número", c.fotos[1].repetidas(G.CONF_DEFECTO) and "Already counted (dotted)" in c.leyenda.text(), c.leyenda.text())
c.siguiente(); girar(600); c.alternar_video()
comprobar("en pausa a mitad de camino no se puede corregir", not c.reproduciendo() and not c.en_punto and not c.b_agregar.isEnabled() and "paused" in c.foto_txt.text().lower(), c.foto_txt.text())
c.mostrar(4); c.siguiente(); hasta_que_pare()
comprobar("al terminar el primer video sigue solo en el primer punto del segundo", c.actual == 5 and c.cap_k == 1 and "Video 2 of 2" in c.tiempo.text(),
          f"{c.actual} {c.cap_k} {c.tiempo.text()}")
c.ir_a_cuadro(pts[7]["cuadro"] + 3)
comprobar("la línea de tiempo lleva al punto más cercano del video que se está viendo", c.actual == 7 and c.cuadro == pts[7]["cuadro"], f"{c.actual} {c.cuadro}")
c.anterior(); comprobar("«Punto anterior» vuelve un punto", c.actual == 6)
c.mostrar(9); c.siguiente(); girar(100)
comprobar("tras el último punto pasa al reporte, suelta el video y dibuja el mapa", c.pila.currentIndex() == 2 and c.cap is None
          and c.r_mapa.pixmap() is not None and not c.r_mapa.pixmap().isNull() and os.path.exists(os.path.join(c.carpeta, "mapa_conteo.jpg")))
comprobar("con todo unido no hay aviso de partes sueltas", c.r_union.count() == 0)
if len(sys.argv) > 5: shutil.copy2(os.path.join(c.carpeta, "mapa_conteo.jpg"), sys.argv[5])

c.poner_paso(0); c.poner_videos([va, vb, vc]); esperar_lectura()
comprobar("un video de otro potrero queda como una parte aparte", c.union is not None and c.union["grupos"] == 2, str(c.union and c.union["grupos"]))
c.contar(); t0 = time.time()
while (c.hilo is not None or c.pila.currentIndex() == 0) and time.time() - t0 < 300: qa.processEvents(); time.sleep(0.02)
c._a_reporte(); girar(50)
comprobar("…y el reporte avisa que hay partes sin unir", c.r_union.count() == 1)
c.poner_paso(0); c.poner_video(os.path.join(raiz, "vuelo", "DJI_9999.JPG")); esperar_lectura()
comprobar("un archivo que no es video: lo dice y no deja contar", "video" in c.estado1.text().lower() and not c.b_contar.isEnabled(), c.estado1.text())
v3.ir("fincas"); v3.close()

print("Una finca por cuenta, cuadre de inventario y Excel")
d9 = os.path.join(raiz, "finca_unica")
b9, l9, _ = P.crear_sesion(d9, "pedro", "llanura-verde-27-sol")
f9 = b9.finca("Finca Prueba Llano", "Pedro Prueba")
r9 = lambda t: {"total": t, "ia": t, "manual": 0, "quitadas": 0}
b9.guardar_conteo(f9, "2026-09-01", r9(200), [])
b9.anotar_movimiento(f9, "2026-09-10", "venta", 20)
b9.anotar_movimiento(f9, "2026-09-15", "nacimiento", 6)
b9.guardar_conteo(f9, "2026-10-01", r9(172), [])
v9 = G.Ventana(b9, l9); v9.show(); girar(80)
comprobar("al entrar abre directo la finca de la cuenta", v9.pila.currentWidget() is v9.p_finca and v9.b_fincas.text() == "My ranch")
pf = v9.p_finca
comprobar("el cuadre se ve: 200 − 20 + 6 = 186 esperadas, contó 172",
          pf.t_cuadre.isVisible() and pf.c_pasos[3][1].text() == "186" and "14 cattle missing" in pf.c_estado.text(), pf.c_estado.text())
comprobar("el hallazgo dice cuántas faltan sin explicar", any("14 cattle missing" in w.findChild(QtWidgets.QLabel).text().lower()
          for w in (pf.avisos.itemAt(i).widget() for i in range(pf.avisos.count())) if w and w.objectName() == "aviso"))
comprobar("la tabla de movimientos muestra lo anotado", pf.t_movs.rowCount() == 2 and pf.t_movs.item(0, 2).text() == "+6")
pf.grafica(True); girar(30)
comprobar("la gráfica pasa a meses", pf.b_g_meses.isChecked() and pf.t_grafica.text().startswith("Cattle at each month"))
v9.grab().save(os.path.join(sal, "agi_cuadre.png"))
if os.environ.get("AGI_CAPTURA_CUADRE"): shutil.copy2(os.path.join(sal, "agi_cuadre.png"), os.environ["AGI_CAPTURA_CUADRE"])
rx = pf.guardar_excel(os.path.join(raiz, "inventario.xlsx"))
comprobar("exporta la finca a Excel", rx and os.path.getsize(rx) > 4000)
v9.nuevo_conteo(); c9 = v9.p_contar
comprobar("en «Nuevo conteo» la finca viene puesta y no se puede cambiar",
          not c9.finca.isEnabled() and c9.finca.currentText() == "Finca Prueba Llano" and c9.propietario.isReadOnly())
c9.potrero.setEditText("Potrero Bajo")
comprobar("el potrero es opcional y se lee del campo", c9.potrero_elegido() == "Potrero Bajo")
v9.close(); b9.cerrar()

print("Revisión al abrir")
b2, l2 = P.abrir_sesion(d, "ana", "clave-larga-de-prueba")
b2.con.execute("UPDATE bitacora SET detalle = 'cambiado' WHERE id = 3"); b2.con.commit()
v2 = G.Ventana(b2, l2); v2.show(); girar(80)
comprobar("bitácora alterada: se avisa al abrir", "audit log" in mens[-1].lower(), mens[-1][:80])
v2.close()
if len(sys.argv) > 2:
    shutil.copy2(os.path.join(sal, "agi_bloqueada.png"), sys.argv[2])
shutil.rmtree(raiz, ignore_errors=True)
print("\nTODO BIEN" if not FALLOS else f"\nFALLARON {len(FALLOS)}: " + "; ".join(FALLOS))
sys.exit(1 if FALLOS else 0)
