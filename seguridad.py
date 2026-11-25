"""Seguridad: llaves de acceso por usuario, firma de reportes y huellas.

Idea general
------------
La base de datos se cifra con una llave aleatoria de 256 bits que nadie teclea.
Cada usuario tiene una "ranura" en llaves.json: la llave de la base envuelta
(AES-256-GCM) con una llave derivada de su contrasena (scrypt). Entrar con la
contrasena correcta es lo unico que permite abrir la base. Hay una ranura mas,
la del codigo de recuperacion que se muestra una sola vez al crear el almacen.

Desde la version 2 de llaves.json cada ranura guarda un par de llaves X25519:
la privada va envuelta con la contrasena y la llave de la base va en un "sobre"
cerrado para la publica. Asi se puede CAMBIAR la llave de la base (al desactivar
a alguien) sin conocer las contrasenas de los demas: basta cerrar un sobre nuevo
para la llave publica de cada uno. Las ranuras de la version 1 se siguen
leyendo y se pasan solas a la version 2 la proxima vez que su dueno entra.

Los intentos fallidos se cuentan en intentos.json: tras 5 seguidos hay que
esperar, cada vez mas. Frena a quien tantea en el teclado; a quien se lleva los
archivos lo frena scrypt.

Los reportes se firman con Ed25519. La llave privada vive dentro de la base
cifrada; la publica se entrega a quien quiera verificar un reporte.

Necesita: cryptography.
"""
import base64
import hashlib
import json
import os
import secrets
import time

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ARCHIVO_LLAVES = "llaves.json"
RANURA_RECUPERACION = "__recuperacion__"
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}      # ~0.1 s y 32 MB por intento: frena el tanteo
LARGO_MINIMO = 10
ARCHIVO_INTENTOS = "intentos.json"
FALLOS_LIBRES = 5                  # a partir del quinto fallo seguido hay que esperar
ESPERA_BASE, ESPERA_MAXIMA = 30, 900          # segundos: 30, 60, 120... hasta 15 minutos
CLAVES_COMUNES = {"1234567890", "0123456789", "0987654321", "12345678910", "1234567891", "1q2w3e4r5t", "qwertyuiop",
                  "qwerty12345", "password123", "password1234", "contraseña1", "contrasena1", "contraseña123",
                  "contrasena123", "administrador", "admin12345", "ganaderia123", "abcdefghij", "1111111111"}


class ErrorAcceso(Exception):
    """Usuario o contrasena incorrectos, o archivo de llaves alterado."""


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def _de_b64(s):
    return base64.b64decode(s.encode("ascii"))


def _derivar(clave, sal, params=None):
    p = params or SCRYPT
    return hashlib.scrypt(clave.encode("utf8"), salt=sal, n=p["n"], r=p["r"], p=p["p"],
                          maxmem=256 * 1024 * 1024, dklen=32)


def validar_clave(clave, usuario=None):
    """Rechaza las contrasenas que se adivinan en pocos intentos."""
    if len(clave) < LARGO_MINIMO:
        raise ValueError(f"The password must have at least {LARGO_MINIMO} characters.")
    baja = clave.lower()
    if baja in CLAVES_COMUNES:
        raise ValueError("That password is one of the most common: choose another.")
    if len(set(baja)) < 5:
        raise ValueError("The password repeats the same characters too much.")
    pasos = {ord(b) - ord(a) for a, b in zip(baja, baja[1:])}
    if pasos <= {1} or pasos <= {-1}:
        raise ValueError("The password can't be a sequence like 123456 or abcdef.")
    if usuario and len(usuario) >= 4 and usuario.lower() in baja:
        raise ValueError("The password must not contain the user name.")


def _envolver(llave_base, nombre, clave):
    sal, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    kek = _derivar(clave, sal)
    # el nombre va como dato asociado: una ranura no sirve bajo otro nombre
    envuelta = AESGCM(kek).encrypt(nonce, llave_base, nombre.encode("utf8"))
    return {"sal": _b64(sal), "nonce": _b64(nonce), "envuelta": _b64(envuelta), "scrypt": dict(SCRYPT)}


def _desenvolver(ranura, nombre, clave):
    kek = _derivar(clave, _de_b64(ranura["sal"]), ranura.get("scrypt"))
    try:
        return AESGCM(kek).decrypt(_de_b64(ranura["nonce"]), _de_b64(ranura["envuelta"]), nombre.encode("utf8"))
    except InvalidTag:
        raise ErrorAcceso("Wrong user or password.") from None


def _leer(carpeta):
    """Lee llaves.json. Si esta danado (corte de luz, disco) usa la copia anterior."""
    ruta = os.path.join(carpeta, ARCHIVO_LLAVES)
    try:
        with open(ruta, encoding="utf8") as fh:
            datos = json.load(fh)
        if not isinstance(datos.get("ranuras"), dict):
            raise ValueError
        return datos
    except (ValueError, AttributeError):
        try:
            with open(ruta + ".bak", encoding="utf8") as fh:
                datos = json.load(fh)
            if not isinstance(datos.get("ranuras"), dict):
                raise ValueError
            return datos
        except (OSError, ValueError, AttributeError):
            raise ErrorAcceso("The key file is damaged and there's no copy. Restore from a backup.") from None


def _escribir(carpeta, datos):
    """Escribe a un temporal, lo baja a disco y lo cambia de un golpe; la version anterior queda en .bak."""
    ruta = os.path.join(carpeta, ARCHIVO_LLAVES)
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf8") as fh:
        json.dump(datos, fh, indent=1)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(ruta):
        try:
            with open(ruta, encoding="utf8") as fh:
                json.load(fh)                           # solo una version sana merece ser la copia
            os.replace(ruta, ruta + ".bak")
        except ValueError:
            pass
    os.replace(tmp, ruta)          # reemplazo atomico: nunca queda a medias


# ------------------------------------------------------- intentos fallidos

def _leer_intentos(carpeta):
    try:
        with open(os.path.join(carpeta, ARCHIVO_INTENTOS), encoding="utf8") as fh:
            d = json.load(fh)
        return {"fallos": int(d.get("fallos", 0)), "hasta": float(d.get("hasta", 0)), "sin_avisar": int(d.get("sin_avisar", 0))}
    except (OSError, ValueError, TypeError, AttributeError):
        return {"fallos": 0, "hasta": 0.0, "sin_avisar": 0}


def _guardar_intentos(carpeta, d):
    ruta = os.path.join(carpeta, ARCHIVO_INTENTOS)
    try:
        with open(ruta + ".tmp", "w", encoding="utf8") as fh:
            json.dump(d, fh)
        os.replace(ruta + ".tmp", ruta)
    except OSError:
        pass                        # no poder anotar el intento no debe impedir entrar


def espera_pendiente(carpeta):
    """Segundos que faltan para poder volver a intentar (0 si se puede ya)."""
    return max(0, int(_leer_intentos(carpeta)["hasta"] - time.time() + 0.999))


def _exigir_turno(carpeta):
    falta = espera_pendiente(carpeta)
    if falta:
        texto = f"{falta} seconds" if falta < 120 else f"{(falta + 59) // 60} minutes"
        raise ErrorAcceso(f"Too many failed attempts. Wait {texto} and try again.")


def _anotar_fallo(carpeta):
    d = _leer_intentos(carpeta)
    d["fallos"] += 1
    d["sin_avisar"] += 1
    if d["fallos"] >= FALLOS_LIBRES:
        d["hasta"] = time.time() + min(ESPERA_BASE * 2 ** (d["fallos"] - FALLOS_LIBRES), ESPERA_MAXIMA)
    _guardar_intentos(carpeta, d)


def _anotar_acierto(carpeta):
    d = _leer_intentos(carpeta)
    if d["fallos"] or d["hasta"]:
        d["fallos"], d["hasta"] = 0, 0.0
        _guardar_intentos(carpeta, d)


def fallos_sin_avisar(carpeta):
    """Cuantos intentos fallidos hubo desde la ultima vez que se pregunto. Los pone en cero:
    quien entra los anota en la bitacora."""
    d = _leer_intentos(carpeta)
    n = d["sin_avisar"]
    if n:
        d["sin_avisar"] = 0
        _guardar_intentos(carpeta, d)
    return n


_ETIQUETA_RANURA = b"agi-ranura-v2"


def _pem_privada(cruda):
    return X25519PrivateKey.from_private_bytes(cruda).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode("ascii")


def _ranura_nueva(llave_base, nombre, clave):
    """Ranura version 2: par de llaves propio; la llave de la base va en un sobre para la publica."""
    priv = X25519PrivateKey.generate()
    cruda = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    publica = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return {"publica": publica, "privada": _envolver(cruda, nombre, clave),
            "sobre": cerrar_sobre(publica, llave_base, _ETIQUETA_RANURA)}


def _abrir_ranura(ranura, nombre, clave):
    """Devuelve (llave de la base, llave nueva si hay un cambio de llave a medias o None)."""
    if "privada" not in ranura:                                   # version 1
        return _desenvolver(ranura, nombre, clave), None
    pem = _pem_privada(_desenvolver(ranura["privada"], nombre, clave))
    try:
        llave = abrir_sobre(pem, ranura["sobre"], _ETIQUETA_RANURA)
        nueva = abrir_sobre(pem, ranura["sobre_nuevo"], _ETIQUETA_RANURA) if "sobre_nuevo" in ranura else None
    except ErrorAcceso:
        raise ErrorAcceso("The key file was altered.") from None
    return llave, nueva


def existe_almacen(carpeta):
    return os.path.exists(os.path.join(carpeta, ARCHIVO_LLAVES))


def usuarios_con_llave(carpeta):
    return sorted(k for k in _leer(carpeta)["ranuras"] if k != RANURA_RECUPERACION)


def crear_almacen(carpeta, usuario, clave):
    """Crea la llave de la base y la primera ranura. Devuelve (llave_base, codigo_recuperacion).
    El codigo de recuperacion solo existe aqui: hay que anotarlo."""
    if existe_almacen(carpeta):
        raise FileExistsError("A key store already exists in this folder.")
    validar_clave(clave, usuario)
    os.makedirs(carpeta, exist_ok=True)
    llave = secrets.token_bytes(32)
    crudo = secrets.token_hex(12).upper()                      # 96 bits
    codigo = "-".join(crudo[i:i + 4] for i in range(0, 24, 4))
    _escribir(carpeta, {"version": 2, "ranuras": {
        usuario: _ranura_nueva(llave, usuario, clave),
        RANURA_RECUPERACION: _ranura_nueva(llave, RANURA_RECUPERACION, codigo)}})
    return llave, codigo


def abrir_almacen2(carpeta, usuario, clave):
    """Como abrir_almacen, pero devuelve (llave, llave_nueva): la segunda solo existe si un
    cambio de llave quedo a medias y hay que terminarlo."""
    _exigir_turno(carpeta)
    datos = _leer(carpeta)
    ranuras = datos["ranuras"]
    try:
        if usuario not in ranuras or usuario == RANURA_RECUPERACION:
            _derivar(clave, b"0" * 16)        # mismo costo: no delata si el usuario existe
            raise ErrorAcceso("Wrong user or password.")
        llave, nueva = _abrir_ranura(ranuras[usuario], usuario, clave)
    except ErrorAcceso:
        _anotar_fallo(carpeta)
        raise
    _anotar_acierto(carpeta)
    if "privada" not in ranuras[usuario]:     # ranura de la version 1: se pasa sola a la 2
        datos["ranuras"][usuario] = _ranura_nueva(llave, usuario, clave)
        datos["version"] = 2
        _escribir(carpeta, datos)
    return llave, nueva


def abrir_almacen(carpeta, usuario, clave):
    """Devuelve la llave de la base si usuario y contrasena son correctos."""
    return abrir_almacen2(carpeta, usuario, clave)[0]


def abrir_con_recuperacion(carpeta, codigo):
    _exigir_turno(carpeta)
    codigo = codigo.strip().upper()
    datos = _leer(carpeta)
    try:
        llave, nueva = _abrir_ranura(datos["ranuras"][RANURA_RECUPERACION], RANURA_RECUPERACION, codigo)
    except ErrorAcceso:
        _anotar_fallo(carpeta)
        raise
    _anotar_acierto(carpeta)
    if "privada" not in datos["ranuras"][RANURA_RECUPERACION]:
        datos["ranuras"][RANURA_RECUPERACION] = _ranura_nueva(llave, RANURA_RECUPERACION, codigo)
        datos["version"] = 2
        _escribir(carpeta, datos)
    return llave


def poner_ranura(carpeta, llave_base, usuario, clave):
    """Crea o reemplaza la ranura de un usuario (alta de usuario o cambio de contrasena)."""
    validar_clave(clave, usuario)
    if usuario == RANURA_RECUPERACION:
        raise ValueError("User name not allowed.")
    datos = _leer(carpeta)
    datos["ranuras"][usuario] = _ranura_nueva(llave_base, usuario, clave)
    _escribir(carpeta, datos)


# ------------------------------------------------- cambio de la llave de la base
# En tres pasos, para que un corte de luz en cualquier punto no deje la base sin llave:
#   1. preparar_rotacion: cada ranura recibe un segundo sobre con la llave nueva.
#   2. quien llama cambia la llave de la base (PRAGMA rekey).
#   3. confirmar_rotacion: el sobre nuevo pasa a ser el unico.
# Si se corta entre 1 y 2, la base aun abre con la llave vieja; entre 2 y 3, con la nueva.
# abrir_almacen2 entrega las dos y quien entra termina el cambio.

def rotacion_pendiente(carpeta):
    return any("sobre_nuevo" in r for r in _leer(carpeta)["ranuras"].values())


def preparar_rotacion(carpeta, quitar=None):
    """Quita la ranura `quitar` y deja listo el cambio de llave. Devuelve la llave nueva."""
    datos = _leer(carpeta)
    if quitar == RANURA_RECUPERACION:
        raise ValueError("The recovery slot can't be removed.")
    datos["ranuras"].pop(quitar, None)
    viejas = sorted(k for k, r in datos["ranuras"].items() if "publica" not in r)
    if viejas:
        nombres = ", ".join("the recovery code" if k == RANURA_RECUPERACION else k for k in viejas)
        raise ValueError(f"The key can't be changed yet: these users still need to sign in once with the new version: {nombres}.")
    nueva = secrets.token_bytes(32)
    for r in datos["ranuras"].values():
        r["sobre_nuevo"] = cerrar_sobre(r["publica"], nueva, _ETIQUETA_RANURA)
    _escribir(carpeta, datos)
    return nueva


def confirmar_rotacion(carpeta):
    datos = _leer(carpeta)
    for r in datos["ranuras"].values():
        if "sobre_nuevo" in r:
            r["sobre"] = r.pop("sobre_nuevo")
    _escribir(carpeta, datos)


def cancelar_rotacion(carpeta):
    datos = _leer(carpeta)
    for r in datos["ranuras"].values():
        r.pop("sobre_nuevo", None)
    _escribir(carpeta, datos)


def quitar_ranura(carpeta, usuario):
    datos = _leer(carpeta)
    if usuario == RANURA_RECUPERACION:
        raise ValueError("The recovery slot can't be removed.")
    datos["ranuras"].pop(usuario, None)
    _escribir(carpeta, datos)


# ----------------------------------------------------------------- huellas

def sha256_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def canonico(obj):
    """JSON con una sola forma posible: es lo que se firma y se compara."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf8")


# ------------------------------------------------------------------- firma

def nueva_llave_firma():
    """Devuelve (privada_pem, publica_pem) como texto."""
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode("ascii")
    return priv_pem, publica_de(priv_pem)


def publica_de(priv_pem):
    priv = serialization.load_pem_private_key(priv_pem.encode("ascii"), password=None)
    return priv.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")


def huella_llave(publica_pem):
    """Huella corta de la llave publica, para compararla a ojo o por telefono."""
    pub = serialization.load_pem_public_key(publica_pem.encode("ascii"))
    crudo = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    h = hashlib.sha256(crudo).hexdigest().upper()[:16]
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def firmar(priv_pem, datos):
    priv = serialization.load_pem_private_key(priv_pem.encode("ascii"), password=None)
    return _b64(priv.sign(datos))


def firma_valida(publica_pem, datos, firma_b64):
    try:
        pub = serialization.load_pem_public_key(publica_pem.encode("ascii"))
        if not isinstance(pub, Ed25519PublicKey):
            return False
        pub.verify(_de_b64(firma_b64), datos)
        return True
    except (InvalidSignature, ValueError):
        return False


# ------------------------------------------------- cifrado para un destinatario
# Un "sobre": cualquiera con la llave publica del destinatario puede cerrarlo,
# solo quien tiene la privada puede abrirlo (X25519 + HKDF-SHA256 + AES-256-GCM).
# Lo usan las ranuras de cada usuario para guardar la llave de la base (etiqueta "agi-ranura-v2").

_ETIQUETA = b"agi-paquete-v1"


def nueva_llave_cifrado():
    """Devuelve (privada_pem, publica_pem) como texto."""
    priv = X25519PrivateKey.generate()
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()).decode("ascii")
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode("ascii")
    return priv_pem, pub_pem


def _publica_cifrado(publica_pem):
    pub = serialization.load_pem_public_key(publica_pem.encode("ascii"))
    if not isinstance(pub, X25519PublicKey):
        raise ValueError("That is not an X25519 public key.")
    return pub


def huella_llave_cifrado(publica_pem):
    crudo = _publica_cifrado(publica_pem).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    h = hashlib.sha256(crudo).hexdigest().upper()[:16]
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def _llave_sobre(compartido, efimera_cruda, destino_cruda, etiqueta=_ETIQUETA):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=etiqueta + efimera_cruda + destino_cruda).derive(compartido)


def cerrar_sobre(publica_pem, datos, etiqueta=_ETIQUETA):
    """Cifra `datos` (bytes) para el dueno de la llave publica. Devuelve un dict serializable."""
    destino = _publica_cifrado(publica_pem)
    destino_cruda = destino.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    efimera = X25519PrivateKey.generate()
    efimera_cruda = efimera.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    llave = _llave_sobre(efimera.exchange(destino), efimera_cruda, destino_cruda, etiqueta)
    nonce = secrets.token_bytes(12)
    return {"efimera": _b64(efimera_cruda), "nonce": _b64(nonce),
            "datos": _b64(AESGCM(llave).encrypt(nonce, datos, etiqueta))}


def abrir_sobre(privada_pem, sobre, etiqueta=_ETIQUETA):
    """Descifra un sobre. Lanza ErrorAcceso si no es para esta llave o fue alterado."""
    try:
        priv = serialization.load_pem_private_key(privada_pem.encode("ascii"), password=None)
        efimera_cruda = _de_b64(sobre["efimera"])
        destino_cruda = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        llave = _llave_sobre(priv.exchange(X25519PublicKey.from_public_bytes(efimera_cruda)), efimera_cruda, destino_cruda, etiqueta)
        return AESGCM(llave).decrypt(_de_b64(sobre["nonce"]), _de_b64(sobre["datos"]), etiqueta)
    except (InvalidTag, KeyError, ValueError, TypeError):
        raise ErrorAcceso("The package is not for this installation or was altered.") from None
