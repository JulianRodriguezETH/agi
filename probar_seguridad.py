"""Pruebas de seguridad, base de datos y analitica. Todo ocurre en una carpeta temporal.

  python probar_seguridad.py

Los nombres de fincas y las cifras son datos de prueba inventados para poder
comparar contra respuestas conocidas; no se guardan en ninguna base real.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datos
import seguridad
import verificar

FALLOS = []


def comprobar(nombre, ok, detalle=""):
    print(("  ok    " if ok else "  FALLA ") + nombre + (f"  [{detalle}]" if detalle else ""))
    if not ok:
        FALLOS.append(nombre)


def falla_con(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="prueba_seg_")
    try:
        print("1. Acceso")
        comprobar("rechaza contraseñas de menos de 10 caracteres",
                  falla_con(ValueError, lambda: seguridad.crear_almacen(tmp, "ana", "corta")))
        llave, codigo = seguridad.crear_almacen(tmp, "ana", "clave-larga-de-ana")
        comprobar("la contraseña correcta abre", seguridad.abrir_almacen(tmp, "ana", "clave-larga-de-ana") == llave)
        comprobar("una contraseña incorrecta no abre",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(tmp, "ana", "clave-larga-de-anA")))
        comprobar("un usuario que no existe no abre",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(tmp, "nadie", "clave-larga-de-ana")))
        comprobar("el código de recuperación abre", seguridad.abrir_con_recuperacion(tmp, codigo.lower()) == llave)
        comprobar("un código de recuperación equivocado no abre",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_con_recuperacion(tmp, "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF")))
        ll = json.load(open(os.path.join(tmp, seguridad.ARCHIVO_LLAVES)))
        comprobar("el archivo de llaves no contiene la contraseña ni la llave",
                  "clave-larga" not in json.dumps(ll) and llave.hex() not in json.dumps(ll))
        # pasar la ranura de ana a otro nombre no debe servir
        ll["ranuras"]["eva"] = ll["ranuras"]["ana"]
        json.dump(ll, open(os.path.join(tmp, seguridad.ARCHIVO_LLAVES), "w"))
        comprobar("copiar la ranura de un usuario bajo otro nombre no abre",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(tmp, "eva", "clave-larga-de-ana")))
        seguridad.quitar_ranura(tmp, "eva")

        print("2. Base cifrada, usuarios y permisos")
        b = datos.Base(tmp, llave, "ana")
        b.iniciar("ana")
        b.poner_config("varias_fincas", "1")          # esta prueba usa varias fincas en una base
        comprobar("la base está cifrada con SQLCipher", b.cifrada)
        b.crear_usuario(llave, "luis", "clave-larga-del-operador", "operador")
        fid = b.finca("Finca Prueba Uno", "Propietario Prueba", "Saravena")
        b.cerrar()
        crudo = open(os.path.join(tmp, datos.ARCHIVO_BASE), "rb").read()
        comprobar("el archivo no deja ver nombres ni la cabecera de SQLite",
                  b"Finca Prueba" not in crudo and b"SQLite format 3" not in crudo and b"Saravena" not in crudo)
        comprobar("no se puede abrir con SQLite normal",
                  falla_con(sqlite3.DatabaseError, lambda: sqlite3.connect(os.path.join(tmp, datos.ARCHIVO_BASE)).execute("SELECT * FROM fincas")))
        comprobar("una llave equivocada no abre la base",
                  falla_con(seguridad.ErrorAcceso, lambda: datos.Base(tmp, b"\x01" * 32, "ana")))
        bl = datos.Base(tmp, seguridad.abrir_almacen(tmp, "luis", "clave-larga-del-operador"), "luis")
        comprobar("el segundo usuario entra con su propia contraseña y es operador", bl.rol == "operador")
        comprobar("un operador no puede crear usuarios",
                  falla_con(datos.SinPermiso, lambda: bl.crear_usuario(llave, "x", "clave-larga-de-x")))
        comprobar("un operador no puede exportar los datos",
                  falla_con(datos.SinPermiso, lambda: bl.exportar_csv(os.path.join(tmp, "exp"))))
        comprobar("un operador no puede borrar conteos", falla_con(datos.SinPermiso, lambda: bl.borrar_conteo(1, "x")))
        bl.cerrar()
        b = datos.Base(tmp, llave, "ana")
        shutil.copy2(os.path.join(tmp, "llaves.json"), os.path.join(tmp, "llaves_que_se_llevo_luis.json"))
        rotada = b.desactivar_usuario("luis")
        llave_vieja, llave = llave, b.llave
        comprobar("al desactivar a alguien la llave de la base cambia", rotada and llave != llave_vieja)
        comprobar("la llave vieja ya no abre la base", falla_con(seguridad.ErrorAcceso, lambda: datos.Base(tmp, llave_vieja, "ana")))
        robo = os.path.join(tmp, "robo"); os.makedirs(robo)
        shutil.copy2(os.path.join(tmp, "llaves_que_se_llevo_luis.json"), os.path.join(robo, "llaves.json"))
        comprobar("la copia de llaves.json que se llevó, con su contraseña, tampoco la abre",
                  falla_con(seguridad.ErrorAcceso, lambda: datos.Base(tmp, seguridad.abrir_almacen(robo, "luis", "clave-larga-del-operador"), "luis")))
        comprobar("la administradora sigue entrando, con la llave nueva", seguridad.abrir_almacen(tmp, "ana", "clave-larga-de-ana") == llave)
        comprobar("el código de recuperación entrega la llave nueva", seguridad.abrir_con_recuperacion(tmp, codigo) == llave)
        comprobar("el cambio de llave queda en la bitácora", "llave_rotada" in [x[3] for x in b.bitacora()] and b.verificar_bitacora()[0])
        comprobar("un usuario desactivado ya no entra",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(tmp, "luis", "clave-larga-del-operador")))

        print("3. Analítica (cifras de prueba con respuesta conocida)")
        f2 = b.finca("Finca Prueba Dos", "Propietario Prueba")
        f3 = b.finca("Finca Prueba Tres", "Otro Propietario")

        def conteo(finca, fecha, total, manual=0, quitadas=0):
            foto = {"nombre": "DJI_0001.JPG", "sha256": "0" * 64, "total": total, "ia": total - manual,
                    "manual": manual, "quitadas": quitadas, "revisada": True, "cajas": []}
            return b.guardar_conteo(finca, fecha, {"total": total, "ia": total - manual, "manual": manual,
                                                   "quitadas": quitadas}, [foto], 0.30, 1.0)

        conteo(fid, "2026-01-10", 300); conteo(fid, "2026-02-10", 306); conteo(fid, "2026-03-10", 270)
        conteo(f2, "2026-01-15", 120); conteo(f2, "2026-03-15", 118)
        conteo(f3, "2026-03-01", 80)
        h = b.historial(fid)
        comprobar("historial: 300 -> 306 -> 270 da cambios +6 y -36", [x[2] for x in h] == [None, 6, -36], str([x[2] for x in h]))
        comprobar("historial: la última caída es de -11.8 %", abs(h[-1][3] + 11.76) < 0.01, f"{h[-1][3]:.2f} %")
        r = {x["finca"]: x for x in b.resumen_fincas()}
        comprobar("resumen: último conteo y anterior por finca",
                  (r["Finca Prueba Uno"]["ultimo"], r["Finca Prueba Uno"]["anterior"]) == (270, 306)
                  and (r["Finca Prueba Dos"]["ultimo"], r["Finca Prueba Dos"]["anterior"]) == (118, 120)
                  and r["Finca Prueba Tres"]["anterior"] is None)
        al = b.alertas(5.0)
        comprobar("alerta de caída > 5 %: solo la finca que bajó 11.8 %", [x["finca"] for x in al] == ["Finca Prueba Uno"],
                  str([x["finca"] for x in al]))
        comprobar("total actual = 270 + 118 + 80 = 468", b.total_actual() == 468, str(b.total_actual()))
        conteo(f2, "2026-03-15", 119)      # el mismo vuelo exportado de nuevo, corregido
        comprobar("sin conteos en corral no hay error medido", b.precision() is None)
        ids = [x["id"] for x in b.conteos_de(f3)]
        b.poner_referencia(ids[0], 84)                       # el programa conto 80, en corral habia 84
        b.poner_referencia([x["id"] for x in b.conteos_de(f2)][0], 115)   # conto 119, habia 115
        pr = b.precision()
        comprobar("error medido contra corral: 80 vs 84 y 119 vs 115 dan 4.1 % de error medio y -0.6 % de sesgo",
                  pr["conteos"] == 2 and abs(pr["error_medio_pct"] - 4.120) < 0.01 and abs(pr["sesgo_pct"] + 0.642) < 0.01,
                  f"{pr['error_medio_pct']:.2f} %, {pr['sesgo_pct']:.2f} %")
        comprobar("re-exportar el mismo vuelo no duplica: vale el último (119) y compara contra 120",
                  [(x[1], x[2]) for x in b.historial(f2)] == [(120, None), (119, -1)], str([(x[1], x[2]) for x in b.historial(f2)]))
        b.exportar_csv(os.path.join(tmp, "exp"))
        comprobar("exporta ranches.csv y counts.csv", os.path.exists(os.path.join(tmp, "exp", "counts.csv"))
                  and len(open(os.path.join(tmp, "exp", "counts.csv"), encoding="utf-8-sig").readlines()) == 8)

        print("4. Bitácora")
        ok, n = b.verificar_bitacora()
        comprobar("la cadena de la bitácora cuadra", ok, f"{n} renglones")
        acciones = [x[3] for x in b.bitacora()]
        comprobar("quedaron anotados usuarios, fincas, conteos y la exportación",
                  {"usuario_creado", "usuario_desactivado", "finca_creada", "conteo_guardado", "datos_exportados"} <= set(acciones))
        # se guarda el texto original para devolverlo tal cual: deshacer con otro replace danaria el renglon cuando el
        # codigo del conteo (que sale de la firma y cambia en cada corrida) trae un "300" propio
        originales = b.con.execute("SELECT id, detalle FROM bitacora WHERE accion = 'conteo_guardado' AND detalle LIKE '%270%'").fetchall()
        b.con.execute("UPDATE bitacora SET detalle = replace(detalle, '270', '300') WHERE accion = 'conteo_guardado' AND detalle LIKE '%270%'")
        b.con.commit()
        ok, donde = b.verificar_bitacora()
        comprobar("cambiar un renglón por SQL se detecta", not ok, f"renglón {donde}")
        for rid, detalle in originales:
            b.con.execute("UPDATE bitacora SET detalle = ? WHERE id = ?", (detalle, rid))
        b.con.commit()
        comprobar("al restaurarlo vuelve a cuadrar", b.verificar_bitacora()[0])
        b.con.execute("DELETE FROM bitacora WHERE id = 5"); b.con.commit()
        ok, donde = b.verificar_bitacora()
        comprobar("borrar un renglón se detecta", not ok, f"falta el {donde}")

        print("5. Reportes firmados")
        carpeta = os.path.join(tmp, "vuelo"); os.makedirs(carpeta)
        for i in (1, 2):
            open(os.path.join(carpeta, f"DJI_000{i}.JPG"), "wb").write(os.urandom(5000))
        fotos = [{"nombre": f"DJI_000{i}.JPG", "sha256": seguridad.sha256_archivo(os.path.join(carpeta, f"DJI_000{i}.JPG")),
                  "total": 10 * i, "ia": 10 * i, "manual": 0, "quitadas": 0, "revisada": True, "cajas": []} for i in (1, 2)]
        cid, codigo_r, man, _ = b.guardar_conteo(f3, "2026-04-01", {"total": 30, "ia": 30, "manual": 0, "quitadas": 0}, fotos, 0.30, 1.0)
        pdf = os.path.join(tmp, "reporte.pdf"); open(pdf, "wb").write(b"%PDF-1.4 contenido de prueba " + os.urandom(2000))
        h_pdf = seguridad.sha256_archivo(pdf)
        sobre = {"manifiesto": man, "pdf_sha256": h_pdf, "llave_publica": b.llave_publica(),
                 "firma": b.firmar(seguridad.canonico({"manifiesto": man, "pdf_sha256": h_pdf}))}
        json.dump(sobre, open(pdf + ".firma.json", "w", encoding="utf8"), ensure_ascii=False)
        open(os.path.join(tmp, "llave_publica.pem"), "w").write(b.llave_publica())
        comprobar("un reporte intacto es válido (con llave del emisor y fotos)",
                  verificar.verificar(pdf, os.path.join(tmp, "llave_publica.pem"), carpeta)[0])
        s2 = json.loads(json.dumps(sobre)); s2["manifiesto"]["total"] = 35
        json.dump(s2, open(pdf + ".firma.json", "w", encoding="utf8"))
        comprobar("cambiar el total (30 -> 35) en el archivo de firma lo invalida", not verificar.verificar(pdf)[0])
        json.dump(sobre, open(pdf + ".firma.json", "w", encoding="utf8"), ensure_ascii=False)
        datos_pdf = bytearray(open(pdf, "rb").read()); datos_pdf[100] ^= 1; open(pdf, "wb").write(datos_pdf)
        comprobar("cambiar un solo bit del PDF lo invalida", not verificar.verificar(pdf)[0])
        datos_pdf[100] ^= 1; open(pdf, "wb").write(datos_pdf)
        open(os.path.join(carpeta, "DJI_0002.JPG"), "ab").write(b"x")
        comprobar("cambiar una foto se detecta", not verificar.verificar(pdf, None, carpeta)[0])
        # un tercero rehace el reporte con otro total y lo firma con SU llave
        priv2, pub2 = seguridad.nueva_llave_firma()
        s3 = json.loads(json.dumps(sobre)); s3["manifiesto"]["total"] = 60; s3["llave_publica"] = pub2
        s3["firma"] = seguridad.firmar(priv2, seguridad.canonico({"manifiesto": s3["manifiesto"], "pdf_sha256": h_pdf}))
        json.dump(s3, open(pdf + ".firma.json", "w", encoding="utf8"))
        comprobar("un reporte re-firmado con otra llave pasa la firma pero NO pasa con la llave del emisor",
                  verificar.verificar(pdf)[0] and not verificar.verificar(pdf, os.path.join(tmp, "llave_publica.pem"))[0])

        print("6. Respaldo")
        destino = os.path.join(tmp, "usb")
        comprobar("sin carpeta elegida no respalda", falla_con(ValueError, lambda: b.respaldar()))
        comprobar("antes del primer respaldo: nunca respaldado y con cambios pendientes",
                  b.dias_sin_respaldo() is None and b.hay_cambios_sin_respaldar())
        b.poner_carpeta_respaldo(destino)
        comprobar("si la carpeta de respaldo no está (USB sin conectar) avisa y no crea nada",
                  falla_con(OSError, lambda: b.respaldar()) and not os.path.exists(destino))
        os.makedirs(destino)
        r1 = b.respaldar()
        comprobar("crea una carpeta con la base y las llaves",
                  sorted(os.listdir(r1)) == sorted([datos.ARCHIVO_BASE, seguridad.ARCHIVO_LLAVES]), os.path.basename(r1))
        crudo = open(os.path.join(r1, datos.ARCHIVO_BASE), "rb").read()
        comprobar("la copia también va cifrada", b"Finca Prueba" not in crudo and b"SQLite format 3" not in crudo)
        comprobar("queda registrado: 0 días sin respaldo y sin cambios pendientes",
                  b.dias_sin_respaldo() < 0.01 and not b.hay_cambios_sin_respaldar())
        n_conteos = b.con.execute("SELECT count(*) FROM conteos").fetchone()[0]
        conteo(f3, "2026-05-01", 77)
        comprobar("un conteo nuevo deja cambios pendientes", b.hay_cambios_sin_respaldar())
        nuevo = os.path.join(tmp, "portatil_nuevo")
        usado = datos.restaurar_respaldo(destino, nuevo)
        br = datos.Base(nuevo, seguridad.abrir_almacen(nuevo, "ana", "clave-larga-de-ana"), "ana")
        comprobar("el respaldo se restaura en otro computador y abre con la misma contraseña",
                  br.rol == "admin" and br.con.execute("SELECT count(*) FROM conteos").fetchone()[0] == n_conteos,
                  f"{n_conteos} conteos")
        comprobar("la copia restaurada trae la misma llave de firma", br.llave_publica() == b.llave_publica())
        comprobar("el respaldo es independiente: no trae el conteo hecho después",
                  br.con.execute("SELECT count(*) FROM conteos WHERE total = 77").fetchone()[0] == 0)
        br.cerrar()
        comprobar("restaurar no pisa un computador que ya tiene datos",
                  falla_con(FileExistsError, lambda: datos.restaurar_respaldo(destino, nuevo)))
        comprobar("una carpeta sin respaldos se rechaza",
                  falla_con(ValueError, lambda: datos.restaurar_respaldo(os.path.join(tmp, "vuelo"), os.path.join(tmp, "otro"))))
        ajena = os.path.join(destino, "fotos_de_la_familia"); os.makedirs(ajena); open(os.path.join(ajena, "a.txt"), "w").write("x")
        for _ in range(datos.MAX_RESPALDOS + 2):
            b.respaldar()
        comprobar(f"se conservan solo los últimos {datos.MAX_RESPALDOS} respaldos",
                  len(datos.respaldos_en(destino)) == datos.MAX_RESPALDOS, str(len(datos.respaldos_en(destino))))
        comprobar("al borrar respaldos viejos no toca otras carpetas del disco", os.path.exists(os.path.join(ajena, "a.txt")))
        comprobar("no quedan copias a medias", not [d for d in os.listdir(destino) if d.endswith(".incompleto")])
        comprobar("el más reciente sí trae el conteo nuevo", (lambda x: (x.con.execute("SELECT count(*) FROM conteos WHERE total = 77").fetchone()[0], x.cerrar())[0])(
            datos.Base(os.path.join(destino, datos.respaldos_en(destino)[0]), llave, "ana")) == 1)
        b.cerrar()

        print("7. Defensas contra tanteo, cortes de luz y archivos dañados")
        d8 = os.path.join(tmp, "ocho")
        for mala, por_que in (("1234567890", "muy usada"), ("aaaaaaaaaabb", "repetitiva"), ("abcdefghijkl", "secuencia"),
                              ("la-clave-de-marta-99", "contiene el usuario")):
            comprobar(f"rechaza una contraseña {por_que}", falla_con(ValueError, lambda m=mala: seguridad.crear_almacen(d8, "marta", m)))
        l8, cod8 = seguridad.crear_almacen(d8, "marta", "caballo-verde-78")
        b8 = datos.Base(d8, l8, "marta"); b8.iniciar("marta")
        b8.crear_usuario(l8, "pedro", "sombrero-azul-41", "operador"); b8.cerrar()
        for _ in range(seguridad.FALLOS_LIBRES):
            falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(d8, "marta", "no-es-la-clave"))
        comprobar("tras 5 fallos seguidos hay que esperar, aun con la contraseña buena",
                  falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(d8, "marta", "caballo-verde-78"))
                  and 0 < seguridad.espera_pendiente(d8) <= seguridad.ESPERA_BASE)
        comprobar("la espera también cubre el código de recuperación", falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_con_recuperacion(d8, cod8)))
        ri = os.path.join(d8, seguridad.ARCHIVO_INTENTOS); it = json.load(open(ri)); it["hasta"] = 0; json.dump(it, open(ri, "w"))
        falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(d8, "marta", "no-es-la-clave"))
        comprobar("cada fallo siguiente dobla la espera", seguridad.ESPERA_BASE < seguridad.espera_pendiente(d8) <= 2 * seguridad.ESPERA_BASE)
        it = json.load(open(ri)); it["hasta"] = 0; json.dump(it, open(ri, "w"))
        import piezas
        s8, _ = piezas.abrir_sesion(d8, "marta", "caballo-verde-78")
        fila = [x for x in s8.bitacora() if x[3] == "intentos_fallidos"]
        comprobar("al entrar, los intentos fallidos quedan en la bitácora", len(fila) == 1 and json.loads(fila[0][4])["cuantos"] == 6, str(fila))
        comprobar("entrar bien pone el contador en cero", seguridad.espera_pendiente(d8) == 0 and json.load(open(ri))["fallos"] == 0)
        comprobar("base y bitácora sanas: la revisión no reporta nada", s8.revisar_integridad() == [])

        # cambio de llave que se queda a medias
        nueva = seguridad.preparar_rotacion(d8); s8.cerrar()
        comprobar("corte de luz antes de cambiar la llave: queda pendiente", seguridad.rotacion_pendiente(d8))
        s8, l8b = piezas.abrir_sesion(d8, "pedro", "sombrero-azul-41")
        comprobar("…y el siguiente que entra lo termina", l8b == nueva and not seguridad.rotacion_pendiente(d8) and s8.con.execute("SELECT count(*) FROM usuarios").fetchone()[0] == 2)
        nueva2 = seguridad.preparar_rotacion(d8); s8._cambiar_llave_de_la_base(nueva2); s8.cerrar()
        s8, l8c = piezas.abrir_sesion(d8, "marta", "caballo-verde-78")
        comprobar("corte de luz después de cambiarla: también se termina al entrar", l8c == nueva2 and not seguridad.rotacion_pendiente(d8)
                  and seguridad.abrir_con_recuperacion(d8, cod8) == nueva2 and s8.verificar_bitacora()[0])

        # llaves.json dañado
        buena = open(os.path.join(d8, "llaves.json")).read()
        seguridad.poner_ranura(d8, s8.llave, "pedro", "sombrero-rojo-52")          # deja la version anterior en .bak
        open(os.path.join(d8, "llaves.json"), "w").write(buena[: len(buena) // 2])
        comprobar("llaves.json cortado por la mitad: se usa la copia anterior", seguridad.abrir_almacen(d8, "marta", "caballo-verde-78") == s8.llave)
        os.remove(os.path.join(d8, "llaves.json.bak"))
        comprobar("sin copia, lo dice claro en vez de fallar raro", falla_con(seguridad.ErrorAcceso, lambda: seguridad.abrir_almacen(d8, "marta", "caballo-verde-78")))
        open(os.path.join(d8, "llaves.json"), "w").write(buena)

        # bitacora alterada
        s8.con.execute("UPDATE bitacora SET detalle = 'otra cosa' WHERE id = 2"); s8.con.commit()
        comprobar("la revisión detecta una bitácora alterada", len(s8.revisar_integridad()) == 1 and "audit log" in s8.revisar_integridad()[0])
        s8.cerrar()

        # almacen de la version anterior (ranuras sin par de llaves)
        import importlib.util
        if os.path.exists("/tmp/seguridad_antes.py"):
            spec = importlib.util.spec_from_file_location("seguridad_v1", "/tmp/seguridad_antes.py"); v1 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v1)
            d1 = os.path.join(tmp, "v1"); lv, codv = v1.crear_almacen(d1, "rosa", "tractor-amarillo-63")
            bv = datos.Base(d1, lv, "rosa"); bv.iniciar("rosa")
            comprobar("un almacén de la versión anterior abre igual", seguridad.abrir_almacen(d1, "rosa", "tractor-amarillo-63") == lv)
            comprobar("…y su ranura pasa sola a la versión nueva", "publica" in json.load(open(os.path.join(d1, "llaves.json")))["ranuras"]["rosa"])
            comprobar("mientras el código de recuperación sea viejo, avisa en vez de cambiar la llave",
                      falla_con(ValueError, lambda: bv.rotar_llave()) and not seguridad.rotacion_pendiente(d1))
            comprobar("tras usar el código una vez, ya se puede cambiar", seguridad.abrir_con_recuperacion(d1, codv) == lv
                      and (bv.rotar_llave() or True) and bv.llave != lv and seguridad.abrir_almacen(d1, "rosa", "tractor-amarillo-63") == bv.llave)
            bv.cerrar()

        print("8. Una finca por cuenta, movimientos y cuadre de inventario")
        d9 = os.path.join(tmp, "finca9"); l9, _ = seguridad.crear_almacen(d9, "pedro", "llanura-verde-27-sol")
        b9 = datos.Base(d9, l9, "pedro"); b9.iniciar("pedro")
        f9 = b9.finca("Finca Prueba Llano", "Pedro Prueba")
        comprobar("cada cuenta maneja una sola finca", b9.una_finca() and b9.finca_propia() == f9)
        comprobar("guardar a nombre de otra finca se rechaza",
                  falla_con(ValueError, lambda: b9.finca("Finca Prueba Otra", "Pedro Prueba")))
        comprobar("la misma finca se encuentra igual", b9.finca("Finca Prueba Llano", "Pedro Prueba") == f9)
        r9 = lambda t: {"total": t, "ia": t, "manual": 0, "quitadas": 0}
        b9.guardar_conteo(f9, "2026-09-01", r9(200), [])
        b9.anotar_movimiento(f9, "2026-09-10", "venta", 20)
        b9.anotar_movimiento(f9, "2026-09-15", "nacimiento", 6)
        b9.guardar_conteo(f9, "2026-10-01", r9(185), [])
        q9 = b9.cuadre(f9)
        comprobar("cuadre: 200 − 20 + 6 = 186 esperadas, 185 contadas", q9["esperadas"] == 186 and q9["diferencia"] == -1)
        comprobar("una res de diferencia está dentro del margen: sin hallazgo", b9.hallazgos(f9) == [])
        comprobar("con la venta anotada, bajar 15 no es una caída", not any(h["tipo"] == "caida" for h in b9.hallazgos(f9)))
        b9.guardar_conteo(f9, "2026-11-01", r9(170), [])
        h9 = b9.hallazgos(f9)
        comprobar("sin movimientos, bajar 15 (−8 %) sí es hallazgo", h9 and h9[0]["tipo"] == "caida" and h9[0]["reses"] == 15)
        b9.anotar_movimiento(f9, "2026-10-20", "muerte", 2)
        h9 = b9.hallazgos(f9)
        comprobar("con 2 muertes anotadas: faltan 13 sin explicar", h9 and h9[0]["tipo"] == "faltan" and h9[0]["reses"] == 13)
        comprobar("movimientos con cantidad cero o tipo inventado se rechazan",
                  falla_con(ValueError, lambda: b9.anotar_movimiento(f9, "2026-11-02", "venta", 0))
                  and falla_con(ValueError, lambda: b9.anotar_movimiento(f9, "2026-11-02", "robo_magico", 3)))
        m9 = b9.movimientos(f9)[0]["id"]
        comprobar("quitar un movimiento exige motivo", falla_con(ValueError, lambda: b9.borrar_movimiento(m9, " ")))
        b9.borrar_movimiento(m9, "anotado dos veces")
        comprobar("movimientos y cuadres quedan en la bitácora encadenada", b9.verificar_bitacora()[0]
                  and any(r[3] == "movimiento_borrado" for r in b9.bitacora()))
        b9.guardar_conteo(f9, "2026-11-15", r9(90), [], potrero="Potrero Bajo")
        b9.guardar_conteo(f9, "2026-11-15", r9(78), [], potrero="Potrero Alto")
        comprobar("los potreros del mismo día se suman", b9.historial(f9)[-1][1] == 168 and len(b9.por_potrero(f9)) == 2)
        comprobar("un día por potreros no se compara con uno de finca entera", b9.historial(f9)[-1][2] is None)
        import excel
        ruta_x = os.path.join(tmp, "inventario.xlsx")
        excel.exportar(b9, ruta_x, f9)
        import openpyxl
        lx = openpyxl.load_workbook(ruta_x)
        comprobar("el Excel trae resumen, conteos, movimientos, cuadre y meses",
                  [h.title for h in lx] == ["Summary", "Counts", "Movements", "Reconciliation", "By month"] and lx["Counts"].max_row == 6)
        comprobar("…y la exportación queda en la bitácora", any(r[3] == "excel_exportado" for r in b9.bitacora()))
        b9.renombrar_finca(f9, "Finca Prueba Llano Grande", "Pedro Prueba", "nombre completo")
        comprobar("renombrar la finca queda anotado y no rompe la firma de los conteos",
                  b9.datos_finca(f9)["nombre"] == "Finca Prueba Llano Grande" and b9.verificar_bitacora()[0])
        b9.cerrar()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nTODO BIEN" if not FALLOS else f"\nFALLARON {len(FALLOS)}: " + "; ".join(FALLOS))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
