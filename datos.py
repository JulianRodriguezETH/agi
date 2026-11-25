"""Base de datos de fincas, conteos y rastreos, con bitacora y analitica.

Un solo archivo (ganaderia.db) cifrado con SQLCipher (AES-256). La llave la
entrega seguridad.abrir_almacen() tras comprobar usuario y contrasena.
Si sqlcipher3 no esta instalado se puede abrir sin cifrar (cifrar=False),
pero entonces cualquiera con acceso al disco lee los datos.

Necesita: sqlcipher3-wheels (cifrado) y cryptography.
"""
import csv
import datetime
import hashlib
import json
import os
import re
import shutil
import uuid

import seguridad

try:
    import sqlcipher3 as _sql
    HAY_CIFRADO = True
except ImportError:                     # pragma: no cover - depende de la instalacion
    import sqlite3 as _sql
    HAY_CIFRADO = False

VERSION = "0.3"
ARCHIVO_BASE = "ganaderia.db"
ROLES = ("admin", "operador")
MAX_RESPALDOS = 10                 # se conservan los ultimos; los mas viejos se borran
DIAS_AVISO_RESPALDO = 7
_NOMBRE_RESPALDO = re.compile(r"^respaldo_\d{8}_\d{6}(_\d+)?$")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY, nombre TEXT NOT NULL UNIQUE, rol TEXT NOT NULL CHECK (rol IN ('admin','operador')),
    activo INTEGER NOT NULL DEFAULT 1, creado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fincas (
    id INTEGER PRIMARY KEY, nombre TEXT NOT NULL, propietario TEXT NOT NULL DEFAULT '',
    municipio TEXT NOT NULL DEFAULT '', notas TEXT NOT NULL DEFAULT '', creado TEXT NOT NULL,
    cliente TEXT NOT NULL DEFAULT '',
    UNIQUE (nombre, propietario, cliente));
CREATE TABLE IF NOT EXISTS conteos (
    id INTEGER PRIMARY KEY, finca_id INTEGER NOT NULL REFERENCES fincas(id),
    fecha_vuelo TEXT NOT NULL, creado TEXT NOT NULL, usuario TEXT NOT NULL,
    total INTEGER NOT NULL, ia INTEGER NOT NULL, manual INTEGER NOT NULL, quitadas INTEGER NOT NULL,
    fotos INTEGER NOT NULL, fotos_revisadas INTEGER NOT NULL, umbral REAL, escala REAL,
    codigo TEXT NOT NULL, manifiesto TEXT NOT NULL, firma TEXT NOT NULL, pdf_sha256 TEXT NOT NULL DEFAULT '',
    importado INTEGER NOT NULL DEFAULT 0, pdf_ruta TEXT NOT NULL DEFAULT '', referencia INTEGER);
CREATE INDEX IF NOT EXISTS conteos_finca ON conteos (finca_id, fecha_vuelo);
CREATE TABLE IF NOT EXISTS conteo_fotos (
    id INTEGER PRIMARY KEY, conteo_id INTEGER NOT NULL REFERENCES conteos(id) ON DELETE CASCADE,
    nombre TEXT NOT NULL, sha256 TEXT NOT NULL, total INTEGER NOT NULL, ia INTEGER NOT NULL,
    manual INTEGER NOT NULL, quitadas INTEGER NOT NULL, revisada INTEGER NOT NULL, cajas TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rastreos (
    id INTEGER PRIMARY KEY, finca_id INTEGER NOT NULL REFERENCES fincas(id),
    fecha_vuelo TEXT NOT NULL, creado TEXT NOT NULL, usuario TEXT NOT NULL,
    animales INTEGER NOT NULL, en_rebano INTEGER NOT NULL, aisladas INTEGER NOT NULL,
    fuera_lindero INTEGER NOT NULL, puntos TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS movimientos (
    id INTEGER PRIMARY KEY, uid TEXT NOT NULL UNIQUE, finca_id INTEGER NOT NULL REFERENCES fincas(id),
    fecha TEXT NOT NULL, tipo TEXT NOT NULL, cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    nota TEXT NOT NULL DEFAULT '', creado TEXT NOT NULL, usuario TEXT NOT NULL, importado INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS movimientos_finca ON movimientos (finca_id, fecha);
CREATE TABLE IF NOT EXISTS bitacora (
    id INTEGER PRIMARY KEY AUTOINCREMENT, momento TEXT NOT NULL, usuario TEXT NOT NULL,
    accion TEXT NOT NULL, detalle TEXT NOT NULL, previo TEXT NOT NULL, hash TEXT NOT NULL);
"""


# Movimientos de ganado que explican por que cambia el inventario entre un conteo y otro: (nombre, signo)
TIPOS_MOVIMIENTO = {
    "compra": ("Purchase", 1), "nacimiento": ("Birth", 1), "entrada": ("Arrived from another ranch", 1),
    "venta": ("Sale", -1), "muerte": ("Death", -1), "salida": ("Left to another ranch", -1),
    "consumo": ("Consumed on the ranch", -1)}
PLURAL_MOVIMIENTO = {"compra": "purchases", "nacimiento": "births", "entrada": "arrivals from another ranch",
                     "venta": "sales", "muerte": "deaths", "salida": "departures to another ranch", "consumo": "consumed on the ranch"}
MARGEN_CUADRE = 2                   # reses de diferencia que se toleran siempre (el conteo puede errar por una o dos)
CARPETA_REPORTES = "reportes"      # dentro de cada respaldo, y en los datos tras recuperarlo


class SinPermiso(Exception):
    pass


def ahora():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _hash_bitacora(previo, momento, usuario, accion, detalle):
    return hashlib.sha256("\x1f".join((previo, momento, usuario, accion, detalle)).encode("utf8")).hexdigest()


def codigo_de(manifiesto_canonico):
    h = hashlib.sha256(manifiesto_canonico).hexdigest().upper()[:12]
    return "-".join(h[i:i + 4] for i in range(0, 12, 4))


class Base:
    """Conexion abierta a nombre de un usuario. Todas las escrituras quedan en la bitacora."""

    def __init__(self, carpeta, llave, usuario, cifrar=True):
        self.carpeta, self.usuario = carpeta, usuario
        self._llave = llave
        self.cifrada = bool(cifrar and HAY_CIFRADO)
        if cifrar and not HAY_CIFRADO:
            raise RuntimeError("sqlcipher3-wheels is missing: install it or open with cifrar=False.")
        self.con = _sql.connect(os.path.join(carpeta, ARCHIVO_BASE))
        if self.cifrada:
            self.con.execute(f"PRAGMA key = \"x'{llave.hex()}'\"")
        try:
            self.con.execute("PRAGMA foreign_keys = ON")
            self.con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except _sql.DatabaseError:
            raise seguridad.ErrorAcceso("The key doesn't open the database.") from None
        self.con.executescript(ESQUEMA)
        # bases creadas con una version anterior: se les anaden las columnas nuevas
        for tabla, columna, tipo in (("fincas", "cliente", "TEXT NOT NULL DEFAULT ''"),
                                     ("conteos", "importado", "INTEGER NOT NULL DEFAULT 0"),
                                     ("conteos", "pdf_ruta", "TEXT NOT NULL DEFAULT ''"),
                                     ("conteos", "referencia", "INTEGER"),
                                     ("conteos", "potrero", "TEXT NOT NULL DEFAULT ''")):
            if columna not in [f[1] for f in self.con.execute(f"PRAGMA table_info({tabla})")]:
                self.con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")
        fila = self.con.execute("SELECT rol, activo FROM usuarios WHERE nombre = ?", (usuario,)).fetchone()
        self.rol = fila[0] if fila and fila[1] else None

    def cerrar(self):
        self.con.close()

    @property
    def llave(self):
        """La llave vigente de la base. Cambia cuando se rota: no guardar copias fuera."""
        return self._llave

    # ----------------------------------------------------------- integridad
    def revisar_integridad(self):
        """Comprueba el archivo de la base y la cadena de la bitacora. Devuelve la lista de
        problemas en palabras sencillas (vacia si todo esta bien)."""
        problemas = []
        try:
            if self.con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                problemas.append("The database file is damaged. Restore the last backup.")
        except _sql.DatabaseError:
            problemas.append("The database file is damaged. Restore the last backup.")
        bien, donde = self.verificar_bitacora()
        if not bien:
            problemas.append(f"The audit log was altered or is incomplete (entry {donde}).")
        return problemas

    # ----------------------------------------------------------- cambio de llave
    def _cambiar_llave_de_la_base(self, nueva):
        if self.cifrada:
            self.con.execute(f"PRAGMA rekey = \"x'{nueva.hex()}'\"")
            self.con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        self._llave = nueva

    def rotar_llave(self, quitar=None, motivo=""):
        """Cambia la llave que cifra la base. Las copias viejas de llaves.json dejan de servir
        para abrirla. `quitar` es el usuario que pierde su ranura en el mismo paso."""
        self._exigir("admin")
        nueva = seguridad.preparar_rotacion(self.carpeta, quitar)
        try:
            self._cambiar_llave_de_la_base(nueva)
        except Exception:
            seguridad.cancelar_rotacion(self.carpeta)
            raise
        seguridad.confirmar_rotacion(self.carpeta)
        self.anotar("llave_rotada", {"motivo": motivo or "manual"})

    def terminar_rotacion(self, nueva, ya_cambiada):
        """Un cambio de llave quedo a medias (se fue la luz): se termina al entrar."""
        if not ya_cambiada:
            self._cambiar_llave_de_la_base(nueva)
        seguridad.confirmar_rotacion(self.carpeta)
        self.anotar("llave_rotada", {"motivo": "an interrupted change was completed"})

    # ----------------------------------------------------------- bitacora
    def _anotar(self, accion, detalle):
        """Cada renglon guarda la huella del anterior: borrar o cambiar uno rompe la cadena."""
        fila = self.con.execute("SELECT hash FROM bitacora ORDER BY id DESC LIMIT 1").fetchone()
        previo = fila[0] if fila else ""
        momento = ahora()
        texto = json.dumps(detalle, ensure_ascii=False, sort_keys=True) if not isinstance(detalle, str) else detalle
        self.con.execute("INSERT INTO bitacora (momento, usuario, accion, detalle, previo, hash) VALUES (?,?,?,?,?,?)",
                         (momento, self.usuario, accion, texto, previo,
                          _hash_bitacora(previo, momento, self.usuario, accion, texto)))

    def anotar(self, accion, detalle=""):
        with self.con:
            self._anotar(accion, detalle)

    def ultimo_hash(self):
        fila = self.con.execute("SELECT hash FROM bitacora ORDER BY id DESC LIMIT 1").fetchone()
        return fila[0] if fila else ""

    def verificar_bitacora(self):
        """Devuelve (True, n_renglones) o (False, id del primer renglon que no cuadra)."""
        previo, esperado_id, n = "", None, 0
        for i, momento, usuario, accion, detalle, prev, h in self.con.execute(
                "SELECT id, momento, usuario, accion, detalle, previo, hash FROM bitacora ORDER BY id"):
            if esperado_id is not None and i != esperado_id:
                return False, esperado_id                 # falta un renglon
            if prev != previo or h != _hash_bitacora(prev, momento, usuario, accion, detalle):
                return False, i
            previo, esperado_id, n = h, i + 1, n + 1
        return True, n

    def bitacora(self, limite=200):
        return self.con.execute("SELECT id, momento, usuario, accion, detalle FROM bitacora "
                                "ORDER BY id DESC LIMIT ?", (limite,)).fetchall()

    # ----------------------------------------------------------- usuarios
    def _exigir(self, *roles):
        if self.rol not in roles:
            raise SinPermiso(f"This action requires the {' or '.join(roles)} role.")

    def iniciar(self, admin):
        """Primer arranque: registra al administrador y crea la llave de firma."""
        with self.con:
            self.con.execute("INSERT INTO usuarios (nombre, rol, creado) VALUES (?, 'admin', ?)", (admin, ahora()))
            priv, pub = seguridad.nueva_llave_firma()
            self.con.execute("INSERT INTO config VALUES ('firma_privada', ?)", (priv,))
            self.con.execute("INSERT INTO config VALUES ('firma_publica', ?)", (pub,))
            self.con.execute("INSERT INTO config VALUES ('instalacion', ?)", (uuid.uuid4().hex,))
            self.rol = "admin"
            self._anotar("almacen_creado", {"admin": admin, "llave_firma": seguridad.huella_llave(pub)})

    def crear_usuario(self, llave, nombre, clave, rol="operador"):
        self._exigir("admin")
        if rol not in ROLES:
            raise ValueError("Unknown role.")
        nombre = nombre.strip()
        if not nombre:
            raise ValueError("The user name is missing.")
        seguridad.validar_clave(clave, nombre)
        with self.con:
            self.con.execute("INSERT INTO usuarios (nombre, rol, creado) VALUES (?,?,?)", (nombre, rol, ahora()))
            self._anotar("usuario_creado", {"nombre": nombre, "rol": rol})
        # el parametro `llave` se conserva por compatibilidad: la vigente es siempre la de esta conexion
        seguridad.poner_ranura(self.carpeta, self._llave, nombre, clave)

    def desactivar_usuario(self, nombre):
        """Quita el acceso y cambia la llave de la base: aunque esa persona se haya llevado una
        copia de llaves.json, su contrasena ya no abre los datos de aqui en adelante.
        Devuelve True si la llave se cambio."""
        self._exigir("admin")
        if nombre == self.usuario:
            raise ValueError("You can't deactivate yourself.")
        with self.con:
            self.con.execute("UPDATE usuarios SET activo = 0 WHERE nombre = ?", (nombre,))
            self._anotar("usuario_desactivado", {"nombre": nombre})
        try:
            self.rotar_llave(quitar=nombre, motivo=f"{nombre} was deactivated")
            return True
        except ValueError as err:               # quedan ranuras de la version 1
            seguridad.quitar_ranura(self.carpeta, nombre)
            self.anotar("llave_no_rotada", {"motivo": str(err)})
            return False

    def cambiar_clave(self, llave, clave_nueva):
        seguridad.poner_ranura(self.carpeta, self._llave, self.usuario, clave_nueva)
        self.anotar("clave_cambiada", {"nombre": self.usuario})

    def restablecer_clave(self, llave, nombre, clave_nueva):
        """El administrador pone una contrasena nueva a otro usuario (tambien lo reactiva)."""
        self._exigir("admin")
        if not self.con.execute("SELECT 1 FROM usuarios WHERE nombre = ?", (nombre,)).fetchone():
            raise ValueError("Unknown user.")
        seguridad.poner_ranura(self.carpeta, self._llave, nombre, clave_nueva)
        with self.con:
            self.con.execute("UPDATE usuarios SET activo = 1 WHERE nombre = ?", (nombre,))
            self._anotar("clave_restablecida", {"nombre": nombre})

    def cambiar_rol(self, nombre, rol):
        self._exigir("admin")
        if rol not in ROLES:
            raise ValueError("Unknown role.")
        if nombre == self.usuario:
            raise ValueError("You can't change your own role.")
        with self.con:
            self.con.execute("UPDATE usuarios SET rol = ? WHERE nombre = ?", (rol, nombre))
            self._anotar("rol_cambiado", {"nombre": nombre, "rol": rol})

    def perfiles(self):
        """Un perfil por usuario: rol, estado, ultimo ingreso, conteos hechos y ultima actividad."""
        self._exigir("admin")
        out = []
        for nombre, rol, activo, creado in self.usuarios():
            ingreso = self.con.execute("SELECT max(momento), count(*) FROM bitacora WHERE usuario = ? "
                                       "AND accion = 'sesion_iniciada'", (nombre,)).fetchone()
            ultima = self.con.execute("SELECT momento, accion FROM bitacora WHERE usuario = ? "
                                      "ORDER BY id DESC LIMIT 1", (nombre,)).fetchone()
            conteos = self.con.execute("SELECT count(*), coalesce(sum(total), 0) FROM conteos WHERE usuario = ?",
                                       (nombre,)).fetchone()
            out.append({"nombre": nombre, "rol": rol, "activo": bool(activo), "creado": creado,
                        "ultimo_ingreso": ingreso[0], "ingresos": ingreso[1], "conteos": conteos[0],
                        "reses_contadas": conteos[1], "ultima_accion": ultima[1] if ultima else None,
                        "ultima_actividad": ultima[0] if ultima else None})
        return out

    def actividad_de(self, nombre, limite=60):
        self._exigir("admin")
        return self.con.execute("SELECT momento, accion, detalle FROM bitacora WHERE usuario = ? "
                                "ORDER BY id DESC LIMIT ?", (nombre, limite)).fetchall()

    def usuarios(self):
        return self.con.execute("SELECT nombre, rol, activo, creado FROM usuarios ORDER BY nombre").fetchall()

    # ---------------------------------------------------------- respaldo
    def config(self, clave, defecto=None):
        fila = self.con.execute("SELECT valor FROM config WHERE clave = ?", (clave,)).fetchone()
        return fila[0] if fila else defecto

    def poner_config(self, clave, valor):
        with self.con:
            self.con.execute("INSERT INTO config (clave, valor) VALUES (?, ?) "
                             "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (clave, str(valor)))

    def poner_carpeta_respaldo(self, carpeta):
        self._exigir("admin")
        self.poner_config("carpeta_respaldo", carpeta)
        self.anotar("respaldo_configurado", {"carpeta": carpeta})

    def dias_sin_respaldo(self):
        """Dias desde el ultimo respaldo; None si nunca se ha hecho."""
        ultimo = self.config("ultimo_respaldo")
        if not ultimo:
            return None
        return (datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(ultimo)).total_seconds() / 86400

    def hay_cambios_sin_respaldar(self):
        return self.config("respaldo_hash", "") != self.ultimo_hash()

    def respaldar(self, destino=None):
        """Copia la base (cifrada) y llaves.json a destino/respaldo_FECHA_HORA.
        Comprueba que la copia abre y esta completa antes de darla por buena, y
        borra los respaldos mas viejos. Devuelve la carpeta creada."""
        self._exigir(*ROLES)
        destino = destino or self.config("carpeta_respaldo")
        if not destino:
            raise ValueError("No backup folder has been chosen.")
        if not os.path.isdir(destino):
            # no se crea: si la USB no esta puesta, el respaldo iria a parar a otro lado
            raise OSError("Can't find the backup folder. Is the USB drive plugged in?")
        pdfs = self.reportes_guardados()
        ocupa = os.path.getsize(os.path.join(self.carpeta, ARCHIVO_BASE)) + sum(os.path.getsize(p) for p in pdfs)
        if shutil.disk_usage(destino).free < 2 * ocupa + (1 << 20):
            raise OSError("Not enough space in the backup folder.")
        nombre = "respaldo_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        final, k = os.path.join(destino, nombre), 1
        while os.path.exists(final):
            k += 1
            final = os.path.join(destino, f"{nombre}_{k}")
        tmp = final + ".incompleto"
        os.makedirs(tmp)
        try:
            copia = _sql.connect(os.path.join(tmp, ARCHIVO_BASE))
            if self.cifrada:
                copia.execute(f"PRAGMA key = \"x'{self._llave.hex()}'\"")
            self.con.backup(copia)          # copia consistente aunque haya una escritura en curso
            copia.close()
            shutil.copy2(os.path.join(self.carpeta, seguridad.ARCHIVO_LLAVES), os.path.join(tmp, seguridad.ARCHIVO_LLAVES))
            # los reportes PDF firmados, con su archivo de firma: si se pierde el computador, no se pierden
            if pdfs:
                os.makedirs(os.path.join(tmp, CARPETA_REPORTES))
                for p in pdfs:
                    shutil.copy2(p, os.path.join(tmp, CARPETA_REPORTES, os.path.basename(p)))
            # comprobar la copia: que abra con la misma llave, este sana y tenga lo mismo
            prueba = _sql.connect(os.path.join(tmp, ARCHIVO_BASE))
            if self.cifrada:
                prueba.execute(f"PRAGMA key = \"x'{self._llave.hex()}'\"")
            sana = prueba.execute("PRAGMA integrity_check").fetchone()[0]
            cuenta = prueba.execute("SELECT (SELECT count(*) FROM conteos), (SELECT count(*) FROM bitacora)").fetchone()
            prueba.close()
            propia = self.con.execute("SELECT (SELECT count(*) FROM conteos), (SELECT count(*) FROM bitacora)").fetchone()
            if sana != "ok" or tuple(cuenta) != tuple(propia):
                raise OSError("The copy doesn't match the database.")
            os.rename(tmp, final)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        # rotacion: solo se tocan carpetas con nuestro nombre y nuestros dos archivos
        viejos = sorted(d for d in os.listdir(destino) if _NOMBRE_RESPALDO.match(d)
                        and os.path.exists(os.path.join(destino, d, ARCHIVO_BASE))
                        and os.path.exists(os.path.join(destino, d, seguridad.ARCHIVO_LLAVES)))
        for d in viejos[:-MAX_RESPALDOS]:
            shutil.rmtree(os.path.join(destino, d), ignore_errors=True)
        with self.con:
            self._anotar("respaldo_hecho", {"carpeta": final})
            self.con.execute("INSERT INTO config (clave, valor) VALUES ('ultimo_respaldo', ?) "
                             "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", (ahora(),))
        self.poner_config("respaldo_hash", self.ultimo_hash())
        return final

    def reportes_guardados(self):
        """Los PDF de los conteos de esta cuenta que siguen en el disco, con su .firma.json."""
        out, vistos = [], set()
        for (ruta,) in self.con.execute("SELECT pdf_ruta FROM conteos WHERE pdf_ruta != '' AND importado = 0"):
            ruta = self.ruta_reporte(ruta)
            if ruta and ruta not in vistos:
                vistos.add(ruta)
                out.append(ruta)
                if os.path.exists(ruta + ".firma.json"):
                    out.append(ruta + ".firma.json")
        return out

    def ruta_reporte(self, ruta):
        """Donde esta hoy el PDF de un conteo: en su ruta original o, tras recuperar un respaldo en otro
        computador, en la carpeta de reportes de los datos. None si no esta en ninguna."""
        if ruta and os.path.exists(ruta):
            return ruta
        if ruta:
            otra = os.path.join(self.carpeta, CARPETA_REPORTES, os.path.basename(ruta.replace("\\", "/")))
            if os.path.exists(otra):
                return otra
        return None

    def resumen_datos(self):
        """Lo que se perderia si se pierde este computador: (conteos, movimientos, reportes)."""
        c, m = self.con.execute("SELECT (SELECT count(*) FROM conteos WHERE importado = 0), "
                                "(SELECT count(*) FROM movimientos WHERE importado = 0)").fetchone()
        return c, m, sum(1 for p in self.reportes_guardados() if p.endswith(".pdf"))

    # ------------------------------------------------------------- firma
    def llave_publica(self):
        return self.con.execute("SELECT valor FROM config WHERE clave = 'firma_publica'").fetchone()[0]

    def firmar(self, datos):
        priv = self.con.execute("SELECT valor FROM config WHERE clave = 'firma_privada'").fetchone()[0]
        return seguridad.firmar(priv, datos)

    # ------------------------------------------------------------ fincas
    def finca(self, nombre, propietario="", municipio="", cliente=""):
        """Devuelve el id de la finca, creandola si no existe.
        cliente: siempre '' (columna que quedo de versiones anteriores)."""
        self._exigir(*ROLES)
        nombre, propietario = nombre.strip(), propietario.strip()
        if not nombre:
            raise ValueError("The ranch name is missing.")
        fila = self.con.execute("SELECT id FROM fincas WHERE nombre = ? AND propietario = ? AND cliente = ?",
                                (nombre, propietario, cliente)).fetchone()
        if fila:
            return fila[0]
        if not cliente and self.una_finca():
            otra = self.con.execute("SELECT nombre FROM fincas WHERE cliente = '' LIMIT 1").fetchone()
            if otra:
                raise ValueError(f"This account belongs to the ranch “{otra[0]}”. Each ranch has its own account.")
        with self.con:
            cur = self.con.execute("INSERT INTO fincas (nombre, propietario, municipio, creado, cliente) VALUES (?,?,?,?,?)",
                                   (nombre, propietario, municipio.strip(), ahora(), cliente))
            self._anotar("finca_creada", {"id": cur.lastrowid, "nombre": nombre, "cliente": cliente})
        return cur.lastrowid

    def una_finca(self):
        """Cada cuenta maneja una sola finca: asi nadie guarda por error el video de una finca a nombre de
        otra. Las pruebas que necesitan varias fincas ponen el ajuste 'varias_fincas'."""
        return self.config("varias_fincas") is None

    def finca_propia(self):
        """Id de la finca de esta cuenta (la primera, si una base vieja tiene varias), o None."""
        f = self.con.execute("SELECT id FROM fincas WHERE cliente = '' ORDER BY id LIMIT 1").fetchone()
        return f[0] if f else None

    def renombrar_finca(self, finca_id, nombre, propietario, motivo):
        """Corrige el nombre o el propietario. Los conteos ya firmados conservan el nombre con que se firmaron."""
        self._exigir("admin")
        nombre, propietario = nombre.strip(), propietario.strip()
        if not nombre:
            raise ValueError("The ranch name is missing.")
        if not motivo.strip():
            raise ValueError("A reason is required.")
        antes = self.datos_finca(finca_id)
        with self.con:
            self.con.execute("UPDATE fincas SET nombre = ?, propietario = ? WHERE id = ?", (nombre, propietario, finca_id))
            self._anotar("finca_renombrada", {"id": finca_id, "antes": [antes["nombre"], antes["propietario"]],
                                              "ahora": [nombre, propietario], "motivo": motivo})

    def fincas(self, cliente=None):
        """[(id, nombre, propietario, municipio, cliente)]. cliente=None: todas; '': solo las propias."""
        if cliente is None:
            return self.con.execute("SELECT id, nombre, propietario, municipio, cliente FROM fincas ORDER BY nombre").fetchall()
        return self.con.execute("SELECT id, nombre, propietario, municipio, cliente FROM fincas WHERE cliente = ? "
                                "ORDER BY nombre", (cliente,)).fetchall()

    def datos_finca(self, finca_id):
        f = self.con.execute("SELECT id, nombre, propietario, municipio, cliente FROM fincas WHERE id = ?", (finca_id,)).fetchone()
        if not f:
            raise ValueError("Unknown ranch.")
        return dict(zip(("id", "nombre", "propietario", "municipio", "cliente"), f))

    # ----------------------------------------------------------- conteos
    def guardar_conteo(self, finca_id, fecha_vuelo, resumen, fotos, umbral=None, escala=None, extra=None, potrero=""):
        """Guarda un conteo firmado. resumen: total, ia, manual, quitadas.
        fotos: lista de dicts nombre, sha256, total, ia, manual, quitadas, revisada, cajas.
        Devuelve (id, codigo, manifiesto, firma). La firma cubre el manifiesto completo,
        que incluye la huella de cada foto y la ultima huella de la bitacora."""
        self._exigir(*ROLES)
        finca = self.con.execute("SELECT nombre, propietario FROM fincas WHERE id = ?", (finca_id,)).fetchone()
        if not finca:
            raise ValueError("Unknown ranch.")
        manifiesto = {
            "version": 1, "tipo": "conteo", "finca": finca[0], "propietario": finca[1],
            "fecha_vuelo": fecha_vuelo, "emitido": ahora(), "usuario": self.usuario,
            "total": resumen["total"], "ia": resumen["ia"], "manual": resumen["manual"],
            "quitadas": resumen["quitadas"], "umbral": umbral, "escala": escala,
            "bitacora_previa": self.ultimo_hash(),
            "fotos": [{k: f[k] for k in ("nombre", "sha256", "total", "ia", "manual", "quitadas", "revisada")}
                      for f in fotos]}
        potrero = (potrero or "").strip()
        if potrero:
            manifiesto["potrero"] = potrero
        if extra:
            manifiesto.update(extra)
        canon = seguridad.canonico(manifiesto)
        codigo, firma = codigo_de(canon), self.firmar(canon)
        with self.con:
            cur = self.con.execute(
                "INSERT INTO conteos (finca_id, fecha_vuelo, creado, usuario, total, ia, manual, quitadas, fotos, "
                "fotos_revisadas, umbral, escala, codigo, manifiesto, firma, potrero) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (finca_id, fecha_vuelo, manifiesto["emitido"], self.usuario, resumen["total"], resumen["ia"],
                 resumen["manual"], resumen["quitadas"], len(fotos), sum(1 for f in fotos if f["revisada"]),
                 umbral, escala, codigo, canon.decode("utf8"), firma, potrero))
            for f in fotos:
                self.con.execute("INSERT INTO conteo_fotos (conteo_id, nombre, sha256, total, ia, manual, quitadas, "
                                 "revisada, cajas) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (cur.lastrowid, f["nombre"], f["sha256"], f["total"], f["ia"], f["manual"],
                                  f["quitadas"], int(f["revisada"]), json.dumps(f.get("cajas", []))))
            self._anotar("conteo_guardado", {"id": cur.lastrowid, "codigo": codigo, "finca": finca[0],
                                             "total": resumen["total"], **({"potrero": potrero} if potrero else {})})
        return cur.lastrowid, codigo, manifiesto, firma

    def registrar_pdf(self, conteo_id, pdf_sha256, ruta=""):
        with self.con:
            self.con.execute("UPDATE conteos SET pdf_sha256 = ?, pdf_ruta = ? WHERE id = ?", (pdf_sha256, ruta, conteo_id))
            self._anotar("reporte_exportado", {"conteo": conteo_id, "pdf_sha256": pdf_sha256})

    def poner_referencia(self, conteo_id, reses_en_corral):
        """Anota el conteo hecho en corral para ese mismo dia: con el se mide el error del programa."""
        self._exigir(*ROLES)
        if reses_en_corral is None or int(reses_en_corral) <= 0:
            raise ValueError("The corral count must be greater than zero.")
        with self.con:
            self.con.execute("UPDATE conteos SET referencia = ? WHERE id = ?", (int(reses_en_corral), conteo_id))
            self._anotar("referencia_anotada", {"conteo": conteo_id, "en_corral": int(reses_en_corral)})

    def precision(self):
        """Error medido contra conteos en corral. Devuelve None si no hay ninguno, o
        {"conteos", "error_medio_pct" (promedio del error absoluto), "sesgo_pct" (si cuenta de mas o de menos)}."""
        filas = self.con.execute("SELECT total, referencia FROM conteos WHERE referencia IS NOT NULL AND referencia > 0").fetchall()
        if not filas:
            return None
        errores = [100.0 * (t - r) / r for t, r in filas]
        return {"conteos": len(filas), "error_medio_pct": sum(abs(e) for e in errores) / len(errores),
                "sesgo_pct": sum(errores) / len(errores)}

    def borrar_conteo(self, conteo_id, motivo):
        self._exigir("admin")
        if not motivo.strip():
            raise ValueError("A reason is required.")
        with self.con:
            fila = self.con.execute("SELECT codigo, total FROM conteos WHERE id = ?", (conteo_id,)).fetchone()
            if not fila:
                raise ValueError("Unknown count.")
            self.con.execute("DELETE FROM conteos WHERE id = ?", (conteo_id,))
            self._anotar("conteo_borrado", {"id": conteo_id, "codigo": fila[0], "total": fila[1], "motivo": motivo})

    # --------------------------------------------------------- analitica
    def historial(self, finca_id):
        """Inventario de la finca en cada fecha de vuelo, en orden:
        [(fecha, total, cambio, cambio_pct, codigo, usuario, potreros)].
        Si ese dia se conto la finca entera, vale ese conteo; si se contaron potreros, la suma del ultimo
        conteo de cada potrero de ese dia. El cambio solo se calcula contra una fecha en la que se contaron
        los mismos potreros (comparar la finca entera con un solo potrero no tendria sentido)."""
        por_fecha = {}
        for fecha, potrero, total, codigo, usuario in self.con.execute(
                "SELECT fecha_vuelo, potrero, total, codigo, usuario FROM conteos WHERE finca_id = ? "
                "ORDER BY fecha_vuelo, id", (finca_id,)):
            # mismo vuelo exportado otra vez: vale el ultimo; el anterior sigue guardado
            por_fecha.setdefault(fecha, {})[potrero or ""] = (total, codigo, usuario)
        filas, previos = [], {}
        for fecha in sorted(por_fecha):
            d = por_fecha[fecha]
            if "" in d:
                total, codigo, usuario = d[""]
                potreros = ()
            else:
                potreros = tuple(sorted(d))
                total = sum(v[0] for v in d.values())
                codigo, usuario = d[potreros[-1]][1], d[potreros[-1]][2]
            previo = previos.get(potreros)
            cambio = None if previo is None else total - previo
            pct = None if not previo else 100.0 * cambio / previo
            filas.append((fecha, total, cambio, pct, codigo, usuario, potreros))
            previos[potreros] = total
        return filas

    def potreros(self, finca_id):
        """Nombres de los potreros que ya se han contado en la finca."""
        return [f[0] for f in self.con.execute("SELECT DISTINCT potrero FROM conteos WHERE finca_id = ? AND potrero != '' "
                                                "ORDER BY potrero", (finca_id,))]

    def por_potrero(self, finca_id):
        """Ultimo conteo de cada potrero: [{"potrero", "fecha", "total"}]."""
        out = []
        for pot in self.potreros(finca_id):
            f = self.con.execute("SELECT fecha_vuelo, total FROM conteos WHERE finca_id = ? AND potrero = ? "
                                 "ORDER BY fecha_vuelo DESC, id DESC LIMIT 1", (finca_id, pot)).fetchone()
            out.append({"potrero": pot, "fecha": f[0], "total": f[1]})
        return out

    def por_mes(self, finca_id, meses=12):
        """Inventario al cierre de cada mes (el ultimo conteo del mes): [("AAAA-MM", total)]."""
        mes = {}
        for h in self.historial(finca_id):
            mes[h[0][:7]] = h[1]
        return sorted(mes.items())[-meses:]

    # ------------------------------------------------------ movimientos
    def anotar_movimiento(self, finca_id, fecha, tipo, cantidad, nota=""):
        """Venta, compra, nacimiento, muerte... con el se cuadra el inventario entre dos conteos."""
        self._exigir(*ROLES)
        if tipo not in TIPOS_MOVIMIENTO:
            raise ValueError("Unknown movement type.")
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError("The quantity must be greater than zero.")
        datetime.date.fromisoformat(fecha)
        if not self.con.execute("SELECT 1 FROM fincas WHERE id = ?", (finca_id,)).fetchone():
            raise ValueError("Unknown ranch.")
        uid = os.urandom(8).hex()
        with self.con:
            cur = self.con.execute("INSERT INTO movimientos (uid, finca_id, fecha, tipo, cantidad, nota, creado, usuario) "
                                   "VALUES (?,?,?,?,?,?,?,?)", (uid, finca_id, fecha, tipo, cantidad, nota.strip(), ahora(),
                                                               self.usuario))
            self._anotar("movimiento_anotado", {"id": cur.lastrowid, "finca": finca_id, "fecha": fecha, "tipo": tipo,
                                                "cantidad": cantidad})
        return cur.lastrowid

    def borrar_movimiento(self, mov_id, motivo):
        self._exigir("admin")
        if not motivo.strip():
            raise ValueError("A reason is required.")
        with self.con:
            f = self.con.execute("SELECT fecha, tipo, cantidad FROM movimientos WHERE id = ?", (mov_id,)).fetchone()
            if not f:
                raise ValueError("Unknown movement.")
            self.con.execute("DELETE FROM movimientos WHERE id = ?", (mov_id,))
            self._anotar("movimiento_borrado", {"id": mov_id, "fecha": f[0], "tipo": f[1], "cantidad": f[2], "motivo": motivo})

    def movimientos(self, finca_id, desde=None, hasta=None):
        """Movimientos de la finca, del mas nuevo al mas viejo. desde (exclusivo) y hasta (inclusivo): 'AAAA-MM-DD'."""
        q, args = "SELECT id, uid, fecha, tipo, cantidad, nota, usuario, importado FROM movimientos WHERE finca_id = ?", [finca_id]
        if desde:
            q += " AND fecha > ?"
            args.append(desde)
        if hasta:
            q += " AND fecha <= ?"
            args.append(hasta)
        return [dict(zip(("id", "uid", "fecha", "tipo", "cantidad", "nota", "usuario", "importado"), f),
                     signo=TIPOS_MOVIMIENTO.get(f[3], ("", 0))[1], nombre=TIPOS_MOVIMIENTO.get(f[3], (f[3], 0))[0])
                for f in self.con.execute(q + " ORDER BY fecha DESC, id DESC", args)]

    def cuadre(self, finca_id, fecha=None, total=None, potreros=None):
        """Compara un conteo con el anterior mas los movimientos anotados entre los dos.
        Sin fecha: el ultimo conteo guardado. Con fecha y total: un conteo que aun no se ha guardado
        (potreros: los que cubre; () o None para la finca entera).
        Devuelve None si no hay un conteo anterior comparable, o
        {"fecha_base", "base", "entradas", "salidas", "detalle", "esperadas", "contadas", "diferencia", "movimientos"}."""
        hist = self.historial(finca_id)
        if fecha is None:
            if not hist:
                return None
            fecha, total, potreros = hist[-1][0], hist[-1][1], hist[-1][6]
            previos = hist[:-1]
        else:
            previos = [h for h in hist if h[0] < fecha]
            if potreros and len(potreros) == 1:
                # un potrero solo, antes de guardar: se compara con el ultimo conteo de ese potrero. Los
                # movimientos se anotan por finca, asi que aqui no entran (no se sabe en que potrero fueron).
                f = self.con.execute("SELECT fecha_vuelo, total FROM conteos WHERE finca_id = ? AND potrero = ? AND "
                                     "fecha_vuelo < ? ORDER BY fecha_vuelo DESC, id DESC LIMIT 1",
                                     (finca_id, potreros[0], fecha)).fetchone()
                if not f:
                    return None
                return {"fecha_base": f[0], "base": f[1], "entradas": 0, "salidas": 0, "detalle": {}, "esperadas": f[1],
                        "contadas": total, "diferencia": total - f[1], "movimientos": 0, "fecha": fecha,
                        "potrero": potreros[0]}
        potreros = tuple(sorted(potreros or ()))
        previos = [h for h in previos if h[6] == potreros]
        if not previos:
            return None
        base_fecha, base = previos[-1][0], previos[-1][1]
        movs = self.movimientos(finca_id, desde=base_fecha, hasta=fecha)
        entradas = sum(m["cantidad"] for m in movs if m["signo"] > 0)
        salidas = sum(m["cantidad"] for m in movs if m["signo"] < 0)
        detalle = {}
        for m in movs:
            detalle[m["tipo"]] = detalle.get(m["tipo"], 0) + m["cantidad"]
        esperadas = base + entradas - salidas
        return {"fecha_base": base_fecha, "base": base, "entradas": entradas, "salidas": salidas, "detalle": detalle,
                "esperadas": esperadas, "contadas": total, "diferencia": total - esperadas, "movimientos": len(movs),
                "fecha": fecha}

    def esperadas_hoy(self, finca_id):
        """Reses que deberia haber hoy: el ultimo conteo de la finca entera mas los movimientos posteriores.
        None si no hay conteo de la finca entera. Devuelve (esperadas, movimientos_despues)."""
        enteras = [h for h in self.historial(finca_id) if not h[6]]
        if not enteras:
            return None
        movs = self.movimientos(finca_id, desde=enteras[-1][0])
        return enteras[-1][1] + sum(m["signo"] * m["cantidad"] for m in movs), len(movs)

    def resumen_fincas(self, cliente=None):
        """Una fila por finca con su ultimo conteo y el cambio contra el anterior."""
        out = []
        for fid, nombre, propietario, municipio, cli in self.fincas(cliente):
            h = self.historial(fid)
            fila = {"id": fid, "finca": nombre, "propietario": propietario, "municipio": municipio, "cliente": cli,
                    "conteos": len(h), "ultimo": None, "fecha": None, "anterior": None, "cambio": None, "cambio_pct": None}
            if h:
                fecha, total, cambio, pct = h[-1][:4]
                fila.update(ultimo=total, fecha=fecha, anterior=h[-2][1] if len(h) > 1 else None, cambio=cambio, cambio_pct=pct)
            out.append(fila)
        return out

    def alertas(self, caida_pct=5.0, cliente=None):
        """Fincas cuyo ultimo conteo bajo mas de `caida_pct` por ciento frente al anterior."""
        return [r for r in self.resumen_fincas(cliente) if r["cambio_pct"] is not None and r["cambio_pct"] <= -caida_pct]

    def hallazgos(self, finca_id, caida_pct=5.0):
        """Lo que el programa noto en el ultimo conteo de la finca. Hoy: la caida frente
        al conteo anterior. (Las reses apartadas del rebano entran cuando haya fotos con GPS.)"""
        return hallazgos_de(self.cuadre(finca_id), caida_pct)

    def total_actual(self, cliente=None):
        """Suma del ultimo conteo de cada finca."""
        return sum(r["ultimo"] for r in self.resumen_fincas(cliente) if r["ultimo"] is not None)

    def conteos_de(self, finca_id):
        """Conteos de la finca, del mas nuevo al mas viejo."""
        return [dict(zip(("id", "fecha_vuelo", "total", "usuario", "codigo", "pdf_ruta", "importado", "referencia", "potrero"), f)) for f in self.con.execute(
            "SELECT id, fecha_vuelo, total, usuario, codigo, pdf_ruta, importado, referencia, potrero FROM conteos WHERE finca_id = ? "
            "ORDER BY fecha_vuelo DESC, id DESC", (finca_id,))]

    # ----------------------------------------------------------- exportar
    def exportar_csv(self, carpeta):
        """Tablas planas para Excel o Power BI. Salen SIN cifrar: queda anotado en la bitacora."""
        self._exigir("admin")
        os.makedirs(carpeta, exist_ok=True)
        with open(os.path.join(carpeta, "ranches.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["ranch_id", "ranch", "owner", "municipality", "counts", "last_count", "date",
                        "previous", "change", "change_pct"])
            for r in self.resumen_fincas():
                w.writerow([r["id"], r["finca"], r["propietario"], r["municipio"], r["conteos"], r["ultimo"],
                            r["fecha"], r["anterior"], r["cambio"],
                            "" if r["cambio_pct"] is None else f"{r['cambio_pct']:.1f}"])
        with open(os.path.join(carpeta, "counts.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["count_id", "ranch_id", "ranch", "paddock", "flight_date", "total", "detected_by_model",
                        "added", "removed", "images", "images_reviewed", "user", "code"])
            for fila in self.con.execute(
                    "SELECT c.id, f.id, f.nombre, c.potrero, c.fecha_vuelo, c.total, c.ia, c.manual, c.quitadas, c.fotos, "
                    "c.fotos_revisadas, c.usuario, c.codigo FROM conteos c JOIN fincas f ON f.id = c.finca_id "
                    "ORDER BY f.nombre, c.fecha_vuelo, c.id"):
                w.writerow(fila)
        with open(os.path.join(carpeta, "movements.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["ranch_id", "ranch", "date", "type", "quantity", "sign", "note", "user"])
            for fid, nombre, *_ in self.fincas():
                for m in reversed(self.movimientos(fid)):
                    w.writerow([fid, nombre, m["fecha"], m["nombre"], m["cantidad"], m["signo"], m["nota"], m["usuario"]])
        self.anotar("datos_exportados", {"carpeta": carpeta})


def hallazgos_de(c, caida_pct=5.0):
    """Hallazgos de un cuadre. Sin movimientos anotados: la caida frente al conteo anterior.
    Con movimientos: las reses que faltan (o sobran) frente a las que deberia haber."""
    if not c:
        return []
    if not c["movimientos"]:
        pct = 100.0 * c["diferencia"] / c["base"] if c["base"] else 0.0
        if pct <= -caida_pct:
            return [{"tipo": "caida", "reses": -c["diferencia"], "pct": pct, "fecha_anterior": c["fecha_base"]}]
        return []
    margen = max(MARGEN_CUADRE, round(c["esperadas"] * caida_pct / 100.0))
    if c["diferencia"] <= -margen:
        return [{"tipo": "faltan", "reses": -c["diferencia"], "esperadas": c["esperadas"], "fecha_anterior": c["fecha_base"]}]
    if c["diferencia"] >= margen:
        return [{"tipo": "sobran", "reses": c["diferencia"], "esperadas": c["esperadas"], "fecha_anterior": c["fecha_base"]}]
    return []


def respaldos_en(carpeta):
    """Carpetas de respaldo validas dentro de `carpeta`, de la mas nueva a la mas vieja."""
    if not os.path.isdir(carpeta):
        return []
    return sorted((d for d in os.listdir(carpeta) if _NOMBRE_RESPALDO.match(d)
                   and os.path.exists(os.path.join(carpeta, d, ARCHIVO_BASE))
                   and os.path.exists(os.path.join(carpeta, d, seguridad.ARCHIVO_LLAVES))), reverse=True)


def restaurar_respaldo(origen, carpeta_datos):
    """Pone un respaldo en un computador sin datos. `origen` es una carpeta respaldo_...
    o la carpeta que las contiene (se toma la mas nueva). Nunca pisa datos existentes."""
    if not os.path.exists(os.path.join(origen, ARCHIVO_BASE)):
        hay = respaldos_en(origen)
        if not hay:
            raise ValueError("That folder has no backup.")
        origen = os.path.join(origen, hay[0])
    if not os.path.exists(os.path.join(origen, seguridad.ARCHIVO_LLAVES)):
        raise ValueError("The backup is missing llaves.json.")
    if seguridad.existe_almacen(carpeta_datos) or os.path.exists(os.path.join(carpeta_datos, ARCHIVO_BASE)):
        raise FileExistsError("This computer already has data; it won't be replaced.")
    os.makedirs(carpeta_datos, exist_ok=True)
    shutil.copy2(os.path.join(origen, ARCHIVO_BASE), os.path.join(carpeta_datos, ARCHIVO_BASE))
    shutil.copy2(os.path.join(origen, seguridad.ARCHIVO_LLAVES), os.path.join(carpeta_datos, seguridad.ARCHIVO_LLAVES))
    if os.path.isdir(os.path.join(origen, CARPETA_REPORTES)):
        shutil.copytree(os.path.join(origen, CARPETA_REPORTES), os.path.join(carpeta_datos, CARPETA_REPORTES), dirs_exist_ok=True)
    return origen


def mismo_disco(a, b):
    """True si las dos carpetas estan en el mismo disco: un respaldo ahi no protege de nada."""
    def existente(ruta):
        ruta = os.path.abspath(ruta)
        while not os.path.exists(ruta) and os.path.dirname(ruta) != ruta:
            ruta = os.path.dirname(ruta)
        return ruta
    try:
        if os.name == "nt":
            return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()
        return os.stat(existente(a)).st_dev == os.stat(existente(b)).st_dev
    except OSError:
        return False
