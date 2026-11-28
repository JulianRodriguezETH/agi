"""Rastreo termico: encuentra manchas de calor en fotos R-JPEG de drones DJI,
las ubica por GPS y separa el rebano de las reses aisladas.

Uso:
  python termica.py --sdk RUTA\\tsdk-core\\lib\\windows\\release_x64 --entrada fotos_termicas\\ --salida resultados\\

Necesita: numpy, opencv-python y el DJI Thermal SDK (gratis en dji.com;
--sdk es la carpeta donde esta libdirp.dll en Windows o libdirp.so en Linux).
Con Pillow instalado (pip install pillow), los rotulos de las imagenes salen en Manrope; sin el, con la letra de OpenCV.

Salidas:
  <foto>_termica.jpg  la foto termica en 4K (--ancho la cambia): el terreno en trama de puntos y cada mancha, en color, marcada
  manchas.csv         una fila por animal: lat, lon, temperatura, area, estado, enlace a Google Maps
  aisladas.kml        los puntos para abrir en Google Earth o Google Maps
  mapa.jpg            croquis: rebano en ambar, aisladas en rojo

Como decide que es una mancha: resta a cada pixel la temperatura de su entorno
(fondo local) y se queda con las zonas mas calientes que el fondo que tengan
el tamano de una res. Por eso funciona de madrugada o de noche; al mediodia el
suelo esta mas caliente que el animal y no sirve.
"""
import argparse
import csv
import ctypes
import math
import os
import re
import struct
import sys

import cv2
import numpy as np

EXT = (".jpg", ".jpeg")
PASO_PIXEL_MM = 0.012  # sensores termicos DJI de 640x512: 12 micras por pixel
FOCAL_POR_MODELO = {"M3T": 9.1, "M3TD": 9.1, "M30T": 9.1, "M4T": 12.0, "ZH20T": 13.5, "H20T": 13.5}


# ---------------------------------------------------------------- temperatura

class _Resolucion(ctypes.Structure):
    _fields_ = [("ancho", ctypes.c_uint32), ("alto", ctypes.c_uint32)]


class _Parametros(ctypes.Structure):
    # las versiones nuevas del SDK anaden campos al final; el relleno evita
    # que el SDK escriba fuera de la estructura
    _fields_ = [("distancia", ctypes.c_float), ("humedad", ctypes.c_float),
                ("emisividad", ctypes.c_float), ("reflejada", ctypes.c_float),
                ("relleno", ctypes.c_float * 28)]


class LectorTermico:
    """Lee la temperatura por pixel de un R-JPEG con el DJI Thermal SDK (libdirp)."""

    def __init__(self, carpeta_sdk):
        win = sys.platform.startswith("win")
        nombre = "libdirp.dll" if win else "libdirp.so"
        ruta = os.path.join(carpeta_sdk, nombre)
        if not os.path.exists(ruta):
            raise FileNotFoundError(f"No encuentro {nombre} en {carpeta_sdk}")
        if win:
            os.add_dll_directory(os.path.abspath(carpeta_sdk))
        aqui = os.getcwd()
        os.chdir(carpeta_sdk)  # libdirp busca libv_list.ini y sus libv_* al lado
        try:
            self._extra = []
            if not win:
                # en Linux hay que cargar antes las dependencias, en orden:
                # primero las auxiliares (libexif, libMicro*), luego las libv_*
                otras = [f for f in sorted(os.listdir(".")) if f.startswith("lib") and ".so" in f and f != nombre]
                for f in [f for f in otras if not f.startswith("libv_")] + [f for f in otras if f.startswith("libv_")]:
                    try:
                        self._extra.append(ctypes.CDLL(os.path.abspath(f)))
                    except OSError:
                        pass
            self.lib = ctypes.CDLL(os.path.abspath(nombre))
        finally:
            os.chdir(aqui)
        L = self.lib
        L.dirp_set_verbose_level.argtypes = [ctypes.c_int]
        L.dirp_set_verbose_level(0)
        L.dirp_create_from_rjpeg.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int32,
                                             ctypes.POINTER(ctypes.c_void_p)]
        L.dirp_create_from_rjpeg.restype = ctypes.c_int32
        L.dirp_destroy.argtypes = [ctypes.c_void_p]
        L.dirp_get_rjpeg_resolution.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Resolucion)]
        L.dirp_get_rjpeg_resolution.restype = ctypes.c_int32
        L.dirp_get_measurement_params.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Parametros)]
        L.dirp_get_measurement_params.restype = ctypes.c_int32
        L.dirp_set_measurement_params.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Parametros)]
        L.dirp_set_measurement_params.restype = ctypes.c_int32
        L.dirp_measure_ex.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int32]
        L.dirp_measure_ex.restype = ctypes.c_int32

    def leer(self, datos, emisividad=0.98, distancia=25.0):
        """datos: bytes del archivo. Devuelve matriz float32 [alto, ancho] en grados C.
        Emisividad 0.98: pelaje y piel. El SDK admite distancia de 1 a 25 m; a mas
        altura la temperatura absoluta sale algo baja, pero la diferencia animal-fondo
        (que es lo que usa la deteccion) se conserva.
        emisividad=None deja los parametros que trae la foto."""
        buf = (ctypes.c_uint8 * len(datos)).from_buffer_copy(datos)
        h = ctypes.c_void_p()
        r = self.lib.dirp_create_from_rjpeg(buf, len(datos), ctypes.byref(h))
        if r != 0:
            raise ValueError(f"No es un R-JPEG termico de DJI o no es compatible (codigo {r})")
        try:
            res = _Resolucion()
            if self.lib.dirp_get_rjpeg_resolution(h, ctypes.byref(res)) != 0:
                raise ValueError("No se pudo leer la resolucion")
            p = _Parametros()
            if emisividad is not None and self.lib.dirp_get_measurement_params(h, ctypes.byref(p)) == 0:
                p.emisividad = emisividad
                p.distancia = distancia
                self.lib.dirp_set_measurement_params(h, ctypes.byref(p))
            out = np.zeros(res.ancho * res.alto, dtype=np.float32)
            r = self.lib.dirp_measure_ex(h, out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
                                         out.nbytes)
            if r != 0:
                raise ValueError(f"El SDK no pudo medir la temperatura (codigo {r})")
            return out.reshape(res.alto, res.ancho)
        finally:
            self.lib.dirp_destroy(h)


# ------------------------------------------------------------------ metadatos

def _exif(datos):
    """Lector EXIF minimo: modelo, distancia focal, fecha y GPS."""
    out = {}
    i = datos.find(b"Exif\x00\x00")
    if i < 0 or i > 200:
        return out
    t = datos[i + 6:i + 6 + 70000]
    if t[:2] == b"II":
        e = "<"
    elif t[:2] == b"MM":
        e = ">"
    else:
        return out

    def ifd(pos):
        entradas = {}
        if pos + 2 > len(t):
            return entradas
        n = struct.unpack(e + "H", t[pos:pos + 2])[0]
        for k in range(n):
            b = t[pos + 2 + 12 * k: pos + 14 + 12 * k]
            if len(b) < 12:
                break
            tag, tipo, cuenta = struct.unpack(e + "HHI", b[:8])
            entradas[tag] = (tipo, cuenta, b[8:12])
        return entradas

    def valor(ent):
        tipo, cuenta, crudo = ent
        tam = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}.get(tipo, 1) * cuenta
        d = crudo[:tam] if tam <= 4 else t[struct.unpack(e + "I", crudo)[0]:][:tam]
        if tipo == 2:
            return d.split(b"\x00")[0].decode("ascii", "replace").strip()
        if tipo in (5, 10):
            f = "II" if tipo == 5 else "ii"
            vals = []
            for k in range(cuenta):
                a, b2 = struct.unpack(e + f, d[8 * k:8 * k + 8])
                vals.append(a / b2 if b2 else 0.0)
            return vals
        if tipo == 3:
            return list(struct.unpack(e + "H" * cuenta, d))
        if tipo == 4:
            return list(struct.unpack(e + "I" * cuenta, d))
        return d

    try:
        ifd0 = ifd(struct.unpack(e + "I", t[4:8])[0])
        if 0x0110 in ifd0:
            out["modelo"] = valor(ifd0[0x0110])
        if 0x8769 in ifd0:
            sub = ifd(valor(ifd0[0x8769])[0])
            if 0x920A in sub:
                out["focal_mm"] = valor(sub[0x920A])[0]
            if 0x9003 in sub:
                out["fecha"] = valor(sub[0x9003])
        if 0x8825 in ifd0:
            g = ifd(valor(ifd0[0x8825])[0])
            if 2 in g and 4 in g:
                la, lo = valor(g[2]), valor(g[4])
                lat = la[0] + la[1] / 60 + la[2] / 3600
                lon = lo[0] + lo[1] / 60 + lo[2] / 3600
                if 1 in g and valor(g[1]).upper().startswith("S"):
                    lat = -lat
                if 3 in g and valor(g[3]).upper().startswith("W"):
                    lon = -lon
                out["lat"], out["lon"] = lat, lon
    except (struct.error, IndexError, ValueError):
        pass
    return out


_XMP = {"lat": "GpsLatitude", "lon": "GpsLong(?:i|ti)tude", "altura": "RelativeAltitude",
        "yaw": "GimbalYawDegree", "pitch": "GimbalPitchDegree", "roll": "GimbalRollDegree",
        "lrf_dist": "LRFTargetDistance"}


def leer_metadatos(datos):
    """Posicion y orientacion de la camara. Los drones DJI las guardan en un bloque
    XMP (etiquetas drone-dji:...). Si falta, usa el GPS del EXIF."""
    m = _exif(datos)
    i = datos.find(b"drone-dji:")
    if i >= 0:
        xmp = datos[max(0, i - 2000): i + 12000].decode("utf8", "replace")
        for clave, etiqueta in _XMP.items():
            r = re.search(r"drone-dji:%s(?:=\"|>)\s*([-+]?\d+(?:\.\d+)?)" % etiqueta, xmp)
            if r:
                m[clave] = float(r.group(1))
    if "focal_mm" not in m or not m["focal_mm"]:
        m["focal_mm"] = FOCAL_POR_MODELO.get(str(m.get("modelo", "")).upper())
    return m


# ------------------------------------------------------------------ deteccion

def detectar_manchas(temp, gsd=None, delta_min=3.0, k_ruido=4.0, area_min=0.2, area_max=2.8,
                     area_res=1.4, grupo_max=25.0, largo_max=3.5):
    """Zonas mas calientes que su entorno, del tamano y la forma de un animal.

    gsd: metros por pixel en el suelo (None = desconocido: se filtra solo por pixeles).
    Devuelve (manchas, umbral usado). Cada mancha: x, y (centro en pixeles), caja,
    area_m2, t_max, delta, animales.
    Con escala conocida se descarta lo que no parece animal:
      - menor que area_min (piedras, ruido)
      - alargado o poco compacto (caminos, cercas)
      - mayor que grupo_max, o un trozo de una zona caliente grande (charcos,
        techos, suelo desnudo) que no este mas caliente que esa zona
    Una mancha entre area_max y grupo_max se toma como varios animales juntos y se
    estima cuantos dividiendo por area_res (m2 que ocupa una res vista desde arriba).
    """
    alto, ancho = temp.shape
    if gsd:
        lado_fondo = int(round(12.0 / gsd))  # ventana de fondo: unos 12 m
    else:
        lado_fondo = ancho // 6
    lado_fondo = int(np.clip(lado_fondo, 31, min(alto, ancho) // 2)) | 1
    # fondo local = mediana en una ventana grande (se calcula a baja resolucion)
    f = max(1, lado_fondo // 25)
    peq = cv2.resize(temp, (ancho // f, alto // f), interpolation=cv2.INTER_AREA)
    lo, hi = np.percentile(peq, 0.5), np.percentile(peq, 99.5)  # un techo caliente no debe quitar resolucion
    esc = 255.0 / max(1e-6, hi - lo)
    med = cv2.medianBlur(np.uint8(np.clip((peq - lo) * esc, 0, 255)), (lado_fondo // f) | 1)
    fondo = cv2.resize(med.astype(np.float32) / esc + lo, (ancho, alto), interpolation=cv2.INTER_LINEAR)
    delta = temp - fondo
    ruido = 1.4826 * float(np.median(np.abs(delta - np.median(delta))))
    umbral = max(delta_min, k_ruido * ruido)
    masc = np.uint8(delta > umbral)
    masc = cv2.morphologyEx(masc, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, etiq, stats, cent = cv2.connectedComponentsWithStats(masc, connectivity=8)

    # zonas calientes grandes (charcos, techos, suelo desnudo, copas de arboles):
    # se buscan contra la temperatura tipica de toda la foto
    zonas, t_zona = None, {}
    if gsd:
        masc_g = np.uint8((temp - float(np.median(temp))) > umbral)
        ng, zonas, st_g, _ = cv2.connectedComponentsWithStats(masc_g, connectivity=8)
        for z in range(1, ng):
            zx, zy, zw, zh, za = st_g[z]
            cortada = zx <= 0 or zy <= 0 or zx + zw >= ancho or zy + zh >= alto
            # grande, o mayor que un animal y cortada por el borde (sigue fuera de la foto)
            if za * gsd * gsd > (area_max if cortada else grupo_max):
                t_zona[z] = float(np.median(temp[zonas == z]))

    manchas = []
    for i in range(1, n):
        x, y, w, h, a_px = stats[i]
        zona = etiq[y:y + h, x:x + w] == i
        t_max = float(temp[y:y + h, x:x + w][zona].max())
        if gsd:
            area = a_px * gsd * gsd
            if area < area_min or area > grupo_max:
                continue
            # un trozo de zona caliente grande no es un animal, salvo que este
            # claramente mas caliente que la zona (un animal parado dentro)
            z = int(zonas[int(round(cent[i][1])), int(round(cent[i][0]))])
            if z in t_zona and t_max < t_zona[z] + umbral:
                continue
            pts = np.argwhere(zona)[:, ::-1].astype(np.float32)
            (_, _), (ra, rb), _ = cv2.minAreaRect(pts)
            largo, corto = (max(ra, rb) + 1) * gsd, (min(ra, rb) + 1) * gsd
            if largo > 5 * corto or area < 0.3 * largo * corto:
                continue                                   # alargado o disperso
            if area <= area_max:
                if largo > largo_max:
                    continue
                animales = 1
            else:
                animales = max(2, int(round(area / area_res)))
        else:
            if a_px < 6 or a_px > 0.02 * alto * ancho:
                continue
            area, animales = None, 1
        manchas.append({"x": float(cent[i][0]), "y": float(cent[i][1]),
                        "caja": (int(x), int(y), int(x + w), int(y + h)),
                        "area_px": int(a_px), "area_m2": area, "t_max": t_max,
                        "delta": float(delta[y:y + h, x:x + w][zona].max()),
                        "borde": bool(x <= 0 or y <= 0 or x + w >= ancho or y + h >= alto),
                        "animales": animales})
    return manchas, umbral


# ------------------------------------------------------------ georreferencia

def gsd_nadir(altura, focal_mm):
    """Metros de suelo por pixel con la camara mirando recto hacia abajo."""
    return altura * PASO_PIXEL_MM / focal_mm


def pixel_a_suelo(px, py, ancho, alto, altura, focal_mm, yaw=0.0, pitch=-90.0):
    """Proyecta un pixel al suelo (plano). Devuelve (este, norte) en metros desde
    el punto bajo el dron, o None si el rayo no toca el suelo.

    yaw: rumbo de la camara en grados desde el norte, sentido horario.
    pitch: -90 mira recto abajo, 0 mira al horizonte.
    """
    f = focal_mm / PASO_PIXEL_MM
    x = (px - ancho / 2.0) / f
    y = (py - alto / 2.0) / f
    ps, th = math.radians(yaw), math.radians(pitch)
    h = (math.sin(ps), math.cos(ps), 0.0)             # rumbo en el plano (E, N, arriba)
    der = (math.cos(ps), -math.sin(ps), 0.0)          # derecha de la imagen
    fr = (math.cos(th) * h[0], math.cos(th) * h[1], math.sin(th))        # eje optico
    ab = (math.sin(th) * h[0], math.sin(th) * h[1], -math.cos(th))       # abajo de la imagen
    rayo = [x * der[k] + y * ab[k] + fr[k] for k in range(3)]
    if rayo[2] >= -1e-6:
        return None
    t = altura / -rayo[2]
    return t * rayo[0], t * rayo[1]


def metros_a_latlon(lat0, lon0, este, norte):
    lat = lat0 + norte / 111320.0
    lon = lon0 + este / (111320.0 * math.cos(math.radians(lat0)))
    return lat, lon


def latlon_a_metros(lat0, lon0, lat, lon):
    return ((lon - lon0) * 111320.0 * math.cos(math.radians(lat0)), (lat - lat0) * 111320.0)


# ------------------------------------------------- rebano, aisladas, lindero

def unir_duplicados(puntos, centros, radio=5.0, margen=6.0):
    """Una misma res sale en varias fotos traslapadas. Primero cada punto se le
    deja a la foto cuyo centro le queda mas cerca, con `margen` metros de
    tolerancia por el error del GPS. Despues, en la franja dudosa, se unen los
    puntos de fotos distintas a menos de `radio` metros: cada punto que queda
    absorbe como mucho un duplicado por foto, para no fundir dos reses vecinas.
    centros: {foto: (este, norte)} del centro de cada foto en el suelo."""
    nombres = list(centros)
    if len(nombres) > 1:
        c = np.array([centros[k] for k in nombres], dtype=np.float64)
        indice = {k: i for i, k in enumerate(nombres)}
        propios = []
        for p in puntos:
            d = np.hypot(c[:, 0] - p["e"], c[:, 1] - p["n"])
            if d[indice[p["foto"]]] <= d.min() + margen:
                propios.append(p)
        puntos = propios
    quedan = []
    for p in sorted(puntos, key=lambda p: -p["delta"]):
        mejor, dmin = None, radio
        for q in quedan:
            if q["foto"] != p["foto"] and p["foto"] not in q["_vistas"]:
                d = math.hypot(q["e"] - p["e"], q["n"] - p["n"])
                if d <= dmin:
                    mejor, dmin = q, d
        if mejor is None:
            p["_vistas"] = set()
            quedan.append(p)
        else:
            mejor["_vistas"].add(p["foto"])
    return quedan


def clasificar(puntos, radio=40.0, minimo_rebano=5):
    """Agrupa los puntos (DBSCAN): dos animales estan juntos si los separan menos
    de `radio` metros, directamente o en cadena. Un grupo con al menos
    `minimo_rebano` animales es rebano; el resto queda como aislada.
    Anade a cada punto: grupo, estado y dist_rebano (m al animal de rebano mas cercano)."""
    n = len(puntos)
    if n == 0:
        return puntos
    xy = np.array([[p["e"], p["n"]] for p in puntos], dtype=np.float64)
    d = np.sqrt(((xy[:, None, :] - xy[None, :, :]) ** 2).sum(-1))
    grupo = [-1] * n
    g = 0
    for i in range(n):
        if grupo[i] >= 0:
            continue
        pila = [i]
        grupo[i] = g
        while pila:
            a = pila.pop()
            for b in np.nonzero(d[a] <= radio)[0]:
                if grupo[b] < 0:
                    grupo[b] = g
                    pila.append(int(b))
        g += 1
    peso = np.array([p.get("animales", 1) for p in puntos])
    tam = {k: int(peso[[j for j in range(n) if grupo[j] == k]].sum()) for k in range(g)}
    en_rebano = np.array([tam[grupo[i]] >= minimo_rebano for i in range(n)])
    for i, p in enumerate(puntos):
        p["grupo"] = grupo[i]
        p["estado"] = "rebano" if en_rebano[i] else "aislada"
        if en_rebano[i]:
            p["dist_rebano"] = 0.0
        elif en_rebano.any():
            p["dist_rebano"] = float(d[i][en_rebano].min())
        else:
            p["dist_rebano"] = None
    return puntos


def leer_lindero(ruta):
    """Lee el primer poligono de un KML: lista de (lat, lon)."""
    txt = open(ruta, encoding="utf8", errors="replace").read()
    r = re.search(r"<coordinates>(.*?)</coordinates>", txt, re.S)
    if not r:
        raise ValueError("El KML no tiene <coordinates>")
    pol = []
    for trozo in r.group(1).split():
        v = trozo.split(",")
        pol.append((float(v[1]), float(v[0])))
    return pol


def dentro(lat, lon, pol):
    """Punto dentro de poligono (regla par-impar)."""
    c = False
    for i in range(len(pol)):
        la1, lo1 = pol[i]
        la2, lo2 = pol[i - 1]
        if (la1 > lat) != (la2 > lat) and lon < (lo2 - lo1) * (lat - la1) / (la2 - la1) + lo1:
            c = not c
    return c


# --------------------------------------------------------------------- salidas

# Paleta de lo caliente (posicion, color BGR): indigo, violeta, magenta, naranja, ambar y un amarillo palido en lo mas
# caliente. El terreno no la usa: va en una trama de puntos color hueso, para que solo lo que es animal lleve color.
_PALETA = ((0.00, (96, 22, 52)), (0.22, (200, 48, 112)), (0.42, (170, 56, 216)), (0.62, (58, 108, 255)),
           (0.84, (70, 184, 255)), (1.00, (176, 234, 255)))
_HUESO = np.array((211, 223, 230), np.float32)          # los puntos del terreno y los rotulos (BGR)
_ROJO = (114, 123, 255)                                 # las aisladas (BGR)
_FUENTES = {}


def _lut_termica():
    xs = np.array([p for p, _ in _PALETA]) * 255.0
    lut = np.zeros((256, 1, 3), np.uint8)
    for c in range(3):
        lut[:, 0, c] = np.interp(np.arange(256), xs, [col[c] for _, col in _PALETA])
    return lut


def _fuente(px):
    """Manrope (carpeta fuentes/) si Pillow esta instalado; si no, None y los rotulos salen con la letra de OpenCV."""
    if px not in _FUENTES:
        try:
            from PIL import ImageFont
            ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fuentes", "Manrope-SemiBold.ttf")
            _FUENTES[px] = ImageFont.truetype(ruta, px)
        except Exception:
            _FUENTES[px] = None
    return _FUENTES[px]


def _sin_adornos(texto):
    return texto.replace("\u00b0", " ").replace("\u00b7", "-").replace("\u00d7", "x")       # la letra de OpenCV solo trae ASCII


def _ancho_texto(texto, px, espacio=0.0):
    f = _fuente(px)
    if f is None:
        return cv2.getTextSize(_sin_adornos(texto), cv2.FONT_HERSHEY_SIMPLEX, px / 27.0, 1)[0][0]
    return int(sum(round(f.getlength(c) + espacio) for c in texto))


def _escribir(img, textos, grosor=1):
    """Escribe sobre img (BGR) una lista de (texto, x, y de arriba, alto en px, color BGR, espacio entre letras)."""
    if not textos:
        return img
    if _fuente(textos[0][3]) is None:
        for t, x, y, px, color, _e in textos:
            cv2.putText(img, _sin_adornos(t), (int(x), int(y + px * 0.9)), cv2.FONT_HERSHEY_SIMPLEX, px / 27.0, color, grosor, cv2.LINE_AA)
        return img
    from PIL import Image, ImageDraw
    lienzo = Image.fromarray(np.ascontiguousarray(img[..., ::-1]))
    d = ImageDraw.Draw(lienzo)
    for t, x, y, px, color, esp in textos:
        f, cx = _fuente(px), int(x)
        for c in t:
            d.text((cx, y), c, font=f, fill=tuple(int(v) for v in color[::-1]))
            cx += round(f.getlength(c) + esp)                                      # paso entero: letras parejas
    return np.ascontiguousarray(np.asarray(lienzo)[..., ::-1])


def falso_color(temp, manchas, titulo, palabra_aislada="AISLADA", ancho_salida=3840):
    """La foto termica lista para mirar, en 4K (ancho_salida pixeles de ancho; el alto sale de la proporcion de la foto).
    El terreno va en una trama fina de puntos color hueso sobre negro (mas grande el punto donde esta mas tibio) y solo
    las manchas detectadas llevan color, del indigo al ambar, con sus isotermas y un resplandor. Cada mancha lleva un
    recuadro fino y una pestana con su numero y su temperatura (rojo las aisladas); a la derecha, la escala.
    Lo tibio que no es animal (charcos, caminos, piedras) se queda en la trama: claro, pero sin color."""
    alto0, ancho0 = temp.shape
    ancho = int(max(640, ancho_salida))
    z = ancho / float(ancho0)                                                      # pixeles de salida por pixel del sensor
    alto = int(round(alto0 * z))
    k = ancho / 1280.0                                                             # todo lo dibujado crece con la salida

    def e(v, minimo=1):
        return max(minimo, int(round(v * k)))

    kf = 1.0 + (k - 1.0) * 0.72                                                    # la letra crece algo menos: queda mas fina
    linea = max(1, int(round(k * 0.6)))
    suave = cv2.bilateralFilter(temp.astype(np.float32), 5, 1.2, 1.6)              # solo para la vista: quita el grano sin borrar siluetas
    cajas = np.zeros((alto0, ancho0), np.float32)
    for m in manchas:
        x1, y1, x2, y2 = m["caja"]
        cajas[max(0, y1 - 3):y2 + 3, max(0, x1 - 3):x2 + 3] = 1.0
    # el fondo de cada punto: el promedio del terreno a su alrededor, sin contar lo que cae dentro de las manchas
    fuera = 1.0 - cajas
    s_f = max(4.0, ancho0 / 16.0)
    peso = cv2.GaussianBlur(fuera, (0, 0), s_f)
    fondo = cv2.GaussianBlur(suave * fuera, (0, 0), s_f) / np.maximum(peso, 1e-3)
    fondo = np.where(peso > 0.02, fondo, float(np.median(suave))).astype(np.float32)
    tope = max([float(m.get("delta", 0.0)) for m in manchas] + [4.0])              # grados sobre el fondo de lo mas caliente
    calor = np.clip((suave - fondo) / tope, 0, 1)
    cajas = np.clip(cv2.GaussianBlur(cajas, (0, 0), 1.5) * 1.6, 0, 1)
    alfa = np.clip((calor - 0.14) / 0.20, 0, 1)
    alfa = alfa * alfa * (3 - 2 * alfa) * cajas                                    # 1 dentro de cada animal, 0 en el terreno

    # --- el terreno, en gris: la temperatura de toda la foto mas el detalle fino (pasto, matas, huellas)
    r_tapa = max(3, int(round(ancho0 / 640.0 * 3))) * 2 + 1
    tapa = cv2.GaussianBlur(cv2.dilate(np.float32(alfa > 0.03), np.ones((r_tapa, r_tapa), np.uint8)), (0, 0), ancho0 / 320.0)
    libre = tapa < 0.05                                                            # todo menos el animal y su borde
    base = suave * (1 - tapa) + fondo * tapa
    t_lo, t_hi = float(np.percentile(base, 1)), float(np.percentile(base, 99.7))
    glo = np.clip((base - t_lo) / max(t_hi - t_lo, 1.0), 0, 1)
    det = base - cv2.GaussianBlur(base, (0, 0), ancho0 / 40.0)
    loc = np.clip(0.5 + det / (2.0 * max(3.0 * float(det[libre].std()) if libre.any() else 0.0, 0.6)), 0, 1)
    gris = np.clip(0.60 * glo + 0.40 * loc, 0, 1) ** 2.1

    G = np.clip(cv2.resize(gris, (ancho, alto), interpolation=cv2.INTER_CUBIC), 0, 1)
    yy, xx = np.mgrid[0:alto, 0:ancho].astype(np.float32)
    paso, r2 = 1.75 * k + 1.75, 0.70710678                                         # trama de puntos a 45 grados
    u, v = (xx + yy) * r2, (xx - yy) * r2
    cu, cv_ = np.round(u / paso) * paso, np.round(v / paso) * paso
    gc = cv2.remap(G, (cu + cv_) * r2, (cu - cv_) * r2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    punto = np.clip(0.56 * paso * np.sqrt(gc) - np.hypot(u - cu, v - cv_) + 0.5, 0, 1)
    del u, v, cu, cv_
    terreno = punto * (0.35 + 0.65 * gc) + 0.06 * G
    d = np.hypot((xx - ancho / 2) / (ancho / 2), (yy - alto / 2) / (alto / 2))
    del xx, yy, punto, gc
    vin = np.clip((d - 0.62) / 0.63, 0, 1)
    vin = 1.0 - vin * vin * (3 - 2 * vin)                                          # se apaga hacia el negro en los bordes
    img = (terreno * vin * 0.84)[..., None] * _HUESO
    del terreno, vin, d

    # --- cruces de registro, muy tenues, como en una mesa de trabajo
    for fx in (0.2, 0.4, 0.6, 0.8):
        for fy in (0.25, 0.5, 0.75):
            px_, py_, b = int(ancho * fx), int(alto * fy), e(5)
            cv2.line(img, (px_ - b, py_), (px_ + b, py_), (52.0, 52.0, 52.0), linea, cv2.LINE_AA)
            cv2.line(img, (px_, py_ - b), (px_, py_ + b), (52.0, 52.0, 52.0), linea, cv2.LINE_AA)

    # --- lo caliente, en color, con sus isotermas y su resplandor
    lut = _lut_termica()
    lima = max(0.5, 0.42 * z)                                                      # lima los escalones de la ampliacion
    C0 = np.clip(cv2.GaussianBlur(cv2.resize(calor, (ancho, alto), interpolation=cv2.INTER_CUBIC), (0, 0), lima), 0, 1)
    A = np.clip(cv2.GaussianBlur(cv2.resize(alfa, (ancho, alto), interpolation=cv2.INTER_CUBIC), (0, 0), lima), 0, 1)
    color = cv2.LUT(cv2.merge([np.uint8(C0 ** 1.3 * 255)] * 3), lut).astype(np.float32)     # la curva deja el ambar para lo mas caliente
    Ci = cv2.GaussianBlur(cv2.resize(cv2.GaussianBlur(calor, (0, 0), ancho0 / 640.0 * 1.5), (ancho, alto), interpolation=cv2.INTER_CUBIC),
                          (0, 0), lima)                                            # mas liso que el color: curvas limpias, sin el grano del sensor
    pend = np.hypot(cv2.Sobel(Ci, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(Ci, cv2.CV_32F, 0, 1, ksize=3)) / 8.0 + 1e-6
    iso = np.zeros_like(C0)
    for nivel in (0.40, 0.56, 0.72, 0.88):                                         # curvas de igual temperatura dentro del animal
        np.maximum(iso, np.clip(1.0 - np.abs(Ci - nivel) / (pend * 0.9 * linea), 0, 1), out=iso)
    iso *= A * np.clip(pend * z * 40, 0, 1)                                        # sin curva donde el calor es parejo
    color = color * (1.0 + 0.22 * iso[..., None]) + 26.0 * iso[..., None]
    A3 = A[..., None]
    img = img * (1 - A3) + color * A3
    chico = (ancho // max(1, int(round(k))), alto // max(1, int(round(k))))        # el resplandor se calcula en pequeno
    luz = cv2.resize(color * A3, chico, interpolation=cv2.INTER_AREA)
    halo = 0.50 * cv2.GaussianBlur(luz, (0, 0), 11 * k / max(1, int(round(k)))) + 0.22 * cv2.GaussianBlur(luz, (0, 0), 3 * k / max(1, int(round(k))))
    img = np.clip(img + cv2.resize(halo, (ancho, alto), interpolation=cv2.INTER_LINEAR), 0, 255)
    del color, A3, luz, halo, iso, pend, Ci
    sombra = e(40)
    img[:sombra] *= np.linspace(0.30, 1.0, sombra, dtype=np.float32)[:, None, None]  # una sombra arriba, bajo el titulo
    img = np.uint8(img)

    # --- recuadros y pestanas
    textos = []
    px_l, esp_l = int(round(11 * kf)), round(1.1 * kf)
    alto_p, relleno = int(round(20 * kf)), int(round(7 * kf))
    for n, m in enumerate(manchas, 1):
        x1, y1, x2, y2 = [int(round(c * z)) for c in m["caja"]]
        mg = e(7)
        x1, y1, x2, y2 = max(1, x1 - mg), max(1, y1 - mg), min(ancho - 2, x2 + mg), min(alto - 2, y2 + mg)
        aislada = m.get("estado") == "aislada"
        color_l = _ROJO if aislada else (236, 240, 244)
        tenue = tuple(int(c * 0.55) for c in color_l)
        cv2.rectangle(img, (x1, y1), (x2, y2), tenue, linea, cv2.LINE_AA)
        brazo = int(max(4 * k, min(11 * k, (x2 - x1) / 4, (y2 - y1) / 4)))
        for ex, ey, sx, sy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x2, y2, -1, -1), (x1, y2, 1, -1)):      # las esquinas, mas vivas
            cv2.line(img, (ex, ey), (ex + sx * brazo, ey), color_l, linea + (1 if k >= 2 else 0), cv2.LINE_AA)
            cv2.line(img, (ex, ey), (ex, ey + sy * brazo), color_l, linea + (1 if k >= 2 else 0), cv2.LINE_AA)
        num = f"{n:02d}"
        txt = f"{m['t_max']:.0f}\u00b0C"
        if m["animales"] > 1:
            txt += f" \u00b7 \u00d7{m['animales']}"
        if aislada:
            txt += f" \u00b7 {palabra_aislada}"
        w_num = _ancho_texto(num, px_l, esp_l) + 2 * relleno
        w_txt = _ancho_texto(txt, px_l, esp_l) + 2 * relleno
        tx = int(min(max(1, x1), ancho - w_num - w_txt - 2))
        ty = y1 - alto_p if y1 - alto_p >= 2 else y1                               # la pestana va sobre el recuadro; si no cabe, dentro
        zona = img[ty:ty + alto_p + 1, tx:tx + w_num + w_txt + 1]
        zona[:] = np.uint8(zona * 0.18)
        cv2.rectangle(img, (tx, ty), (tx + w_num, ty + alto_p), color_l, -1, cv2.LINE_AA)               # el numero, en una ficha llena
        cv2.rectangle(img, (tx, ty), (tx + w_num + w_txt, ty + alto_p), color_l, linea, cv2.LINE_AA)
        y_txt = ty + int(round((alto_p - px_l * 1.32) / 2))
        textos.append((num, tx + relleno, y_txt, px_l, (12, 12, 12), esp_l))
        textos.append((txt, tx + w_num + relleno, y_txt, px_l, color_l, esp_l))

    # --- titulo, escala y marcas de las esquinas
    px_t, esp_t = int(round(11 * kf)), round(1.4 * kf)
    partes = [p.strip() for p in titulo.split("   ") if p.strip()]
    if partes:
        textos.append((partes[0].upper(), e(18), e(15), px_t, (240, 240, 240), esp_t))
        resto = "  \u00b7  ".join(p.upper() for p in partes[1:])
        if resto:
            textos.append((resto, e(18) + _ancho_texto(partes[0].upper(), px_t, esp_t) + e(22), e(15), px_t, (150, 150, 150), esp_t))
    t_med = float(np.median(fondo))
    e_hi, e_lo = t_med + tope, t_lo
    bx, by, bh, bw = ancho - e(24), e(62), int(min(e(200), alto - e(130))), e(5)
    ts = e_hi - (np.arange(bh, dtype=np.float32) / max(1, bh - 1)) * (e_hi - e_lo)
    cs = np.clip((ts - t_med) / tope, 0, 1)
    a_s = np.clip((cs - 0.14) / 0.20, 0, 1)[:, None]
    gris_s = (np.clip((ts - e_lo) / max(t_med + 0.14 * tope - e_lo, 0.5), 0, 1) * 0.72)[:, None] * _HUESO[None, :]
    barra = cv2.LUT(cv2.merge([np.uint8(cs ** 1.3 * 255)[:, None]] * 3), lut)[:, 0].astype(np.float32) * a_s + gris_s * (1 - a_s)
    img[by:by + bh, bx:bx + bw] = np.uint8(barra)[:, None, :]
    px_e, esp_e = int(round(10 * kf)), round(0.7 * kf)
    cada = next(c for c in (1, 2, 5, 10, 20, 50) if (e_hi - e_lo) / c <= 6)        # marcas de la escala, en grados redondos
    for g in range(int(math.ceil(e_lo / cada)) * cada, int(math.floor(e_hi)) + 1, cada):
        gy = by + int(round((e_hi - g) / max(e_hi - e_lo, 1e-6) * (bh - 1)))
        if by <= gy < by + bh:
            cv2.line(img, (bx - e(6), gy), (bx - e(2), gy), (170, 170, 170), linea, cv2.LINE_AA)
            txt = f"{g}\u00b0C"
            textos.append((txt, bx - e(11) - _ancho_texto(txt, px_e, esp_e), gy - int(px_e * 0.66), px_e, (200, 200, 200), esp_e))
    for ex, ey, sx, sy in ((e(12), e(12), 1, 1), (ancho - e(13), e(12), -1, 1), (ancho - e(13), alto - e(13), -1, -1), (e(12), alto - e(13), 1, -1)):
        cv2.line(img, (ex, ey), (ex + sx * e(14), ey), (120, 120, 120), linea, cv2.LINE_AA)
        cv2.line(img, (ex, ey), (ex, ey + sy * e(14)), (120, 120, 120), linea, cv2.LINE_AA)
    px_p, esp_p = int(round(9 * kf)), round(1.3 * kf)
    pie = f"SENSOR {ancho0} \u00d7 {alto0}  \u00b7  AGI"
    textos.append((pie, ancho - e(20) - _ancho_texto(pie, px_p, esp_p), alto - e(30), px_p, (120, 120, 120), esp_p))
    return _escribir(img, textos, linea)


def dibujar_mapa(puntos, ruta, lado=2160):
    """El mapa de lo encontrado, con el norte arriba y en el mismo lenguaje de las fotos: fondo negro, cuadricula de
    puntos, el rebano en ambar y cada aislada en rojo con su pestana (numero y distancia al rebano)."""
    if not puntos:
        return
    k = lado / 900.0
    kf = 1.0 + (k - 1.0) * 0.72
    linea = max(1, int(round(k * 0.6)))

    def e(v):
        return max(1, int(round(v * k)))

    este = np.array([p["e"] for p in puntos]); norte = np.array([p["n"] for p in puntos])
    cx, cy = (este.min() + este.max()) / 2, (norte.min() + norte.max()) / 2
    ext = max(este.max() - este.min(), norte.max() - norte.min(), 50.0) * 1.25
    esc = (lado - e(80)) / ext
    img = np.full((lado, lado, 3), 9, dtype=np.uint8)

    def xy(pe, pn):
        return int(lado / 2 + (pe - cx) * esc), int(lado / 2 - (pn - cy) * esc)

    paso = 10 ** math.floor(math.log10(ext / 3))
    for m in (5, 2, 1):
        if ext / (paso * m) >= 3:
            paso *= m
            break
    punteo = tuple(int(c * 0.36) for c in _HUESO)
    salto = e(6)
    v = math.floor((cx - ext / 2) / paso) * paso
    while v < cx + ext / 2:
        x = xy(v, 0)[0]
        if 0 <= x < lado - linea:
            for y in range(0, lado, salto):
                img[y:y + linea, x:x + linea] = punteo
        v += paso
    v = math.floor((cy - ext / 2) / paso) * paso
    while v < cy + ext / 2:
        y = xy(0, v)[1]
        if 0 <= y < lado - linea:
            for x in range(0, lado, salto):
                img[y:y + linea, x:x + linea] = punteo
        v += paso
    ambar = (70, 184, 255)
    luz = np.zeros((lado, lado, 3), np.float32)
    for p in puntos:
        rebano = p["estado"] == "rebano"
        cv2.circle(luz, xy(p["e"], p["n"]), e(4 if rebano else 6), ambar if rebano else _ROJO, -1, cv2.LINE_AA)
    img = np.uint8(np.clip(img + 0.55 * cv2.GaussianBlur(luz, (0, 0), 9 * k), 0, 255))     # un resplandor bajo cada punto
    for p in puntos:
        if p["estado"] == "rebano":
            cv2.circle(img, xy(p["e"], p["n"]), e(4), ambar, -1, cv2.LINE_AA)
    textos, usados = [], []
    px_l, esp_l = int(round(11 * kf)), round(1.1 * kf)
    alto_p, relleno = int(round(20 * kf)), int(round(7 * kf))
    for p in puntos:
        if p["estado"] != "rebano":
            c = xy(p["e"], p["n"])
            cv2.circle(img, c, e(5), _ROJO, -1, cv2.LINE_AA)
            cv2.circle(img, c, e(11), _ROJO, linea, cv2.LINE_AA)
            d = p.get("dist_rebano")
            num = f"#{p['id']}"
            txt = f"{d:.0f} M DEL REBANO" if d else ""
            w_num = _ancho_texto(num, px_l, esp_l) + 2 * relleno
            w_txt = _ancho_texto(txt, px_l, esp_l) + 2 * relleno if txt else 0
            tw = w_num + w_txt
            tx = c[0] + e(18) if c[0] + e(18) + tw < lado - 4 else c[0] - e(18) - tw   # que no se salga
            ty = int(np.clip(c[1] - alto_p // 2, e(34), lado - alto_p - 4))
            while any(abs(ty - uy) < alto_p + 4 and abs(tx - ux) < tw for ux, uy in usados):
                ty += alto_p + e(5)                                                # que no se encimen
            usados.append((tx, ty))
            zona = img[ty:ty + alto_p + 1, max(0, tx):tx + tw + 1]
            zona[:] = np.uint8(zona * 0.18)
            cv2.rectangle(img, (tx, ty), (tx + w_num, ty + alto_p), _ROJO, -1, cv2.LINE_AA)         # el numero, en una ficha llena
            cv2.rectangle(img, (tx, ty), (tx + tw, ty + alto_p), _ROJO, linea, cv2.LINE_AA)
            y_txt = ty + int(round((alto_p - px_l * 1.32) / 2))
            textos.append((num, tx + relleno, y_txt, px_l, (12, 12, 12), esp_l))
            if txt:
                textos.append((txt, tx + w_num + relleno, y_txt, px_l, _ROJO, esp_l))
    n_reb = sum(p["animales"] for p in puntos if p["estado"] == "rebano")
    n_ais = sum(1 for p in puntos if p["estado"] != "rebano")
    px_t, esp_t = int(round(11 * kf)), round(1.4 * kf)
    cab = f"REBANO {n_reb}"
    textos.append((cab, e(18), e(15), px_t, (240, 240, 240), esp_t))
    textos.append((f"AISLADAS {n_ais}", e(18) + _ancho_texto(cab, px_t, esp_t) + e(22), e(15), px_t, _ROJO, esp_t))
    resto = f"CUADRICULA {paso:g} M  \u00b7  NORTE ARRIBA"
    textos.append((resto, lado - e(20) - _ancho_texto(resto, px_t, esp_t), e(15), px_t, (150, 150, 150), esp_t))
    for ex, ey, sx, sy in ((e(12), e(12), 1, 1), (lado - e(13), e(12), -1, 1), (lado - e(13), lado - e(13), -1, -1), (e(12), lado - e(13), 1, -1)):
        cv2.line(img, (ex, ey), (ex + sx * e(14), ey), (120, 120, 120), linea, cv2.LINE_AA)
        cv2.line(img, (ex, ey), (ex, ey + sy * e(14)), (120, 120, 120), linea, cv2.LINE_AA)
    cv2.imwrite(ruta, _escribir(img, textos, linea), [cv2.IMWRITE_JPEG_QUALITY, 90])


def escribir_kml(puntos, ruta):
    with open(ruta, "w", encoding="utf8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>\n')
        fh.write("<name>Reses aisladas</name>\n")
        for p in puntos:
            if p["estado"] == "rebano" or p.get("lat") is None:
                continue
            d = p.get("dist_rebano")
            desc = f"Temperatura {p['t_max']:.1f} C. Foto {p['foto']}." + (f" A {d:.0f} m del rebano." if d else "")
            if p.get("fuera_lindero"):
                desc += " FUERA DEL LINDERO."
            fh.write(f"<Placemark><name>Res aislada #{p['id']}</name><description>{desc}</description>"
                     f"<Point><coordinates>{p['lon']:.7f},{p['lat']:.7f},0</coordinates></Point></Placemark>\n")
        fh.write("</Document></kml>\n")


# ---------------------------------------------------------------------- nucleo

def analizar(fotos, delta=3.0, radio_rebano=40.0, minimo_rebano=5, radio_duplicado=5.0,
             lindero=None, informar=print):
    """fotos: iterable de (nombre, temperatura[alto, ancho], metadatos).
    metadatos: dict con lat, lon, altura (m sobre el suelo), yaw, pitch, focal_mm.
    Devuelve (puntos ubicados y clasificados, [(nombre, temp, manchas)], manchas sin coordenada)."""
    puntos, por_foto, centros, origen, sin_geo = [], [], {}, None, 0
    for nombre, temp, meta in fotos:
        altura, yaw, pitch = meta.get("altura"), meta.get("yaw"), meta.get("pitch")
        focal = meta.get("focal_mm")
        alto, ancho = temp.shape
        geo = None not in (altura, yaw, pitch, focal, meta.get("lat"), meta.get("lon")) and altura > 2
        # el tamano en metros solo es fiable mirando casi recto hacia abajo
        gsd = gsd_nadir(altura, focal) if geo and pitch <= -60 else None
        manchas, umbral = detectar_manchas(temp, gsd=gsd, delta_min=delta)
        if geo and origen is None:
            origen = (meta["lat"], meta["lon"])

        def ubicar(px, py):
            s = pixel_a_suelo(px, py, ancho, alto, altura, focal, yaw, pitch)
            if not s or math.hypot(*s) > 15 * altura:
                return None
            lat, lon = metros_a_latlon(meta["lat"], meta["lon"], s[0], s[1])
            return lat, lon, latlon_a_metros(origen[0], origen[1], lat, lon)

        if geo:
            c = ubicar(ancho / 2.0, alto / 2.0)
            if c:
                centros[nombre] = c[2]
        for m in manchas:
            m["foto"] = nombre
            m["lat"] = m["lon"] = m["e"] = m["n"] = None
            u = ubicar(m["x"], m["y"]) if geo else None
            if u:
                m["lat"], m["lon"], (m["e"], m["n"]) = u
                puntos.append(m)
            else:
                sin_geo += 1
        por_foto.append((nombre, temp, manchas))
        informar(f"{nombre}: {len(manchas)} manchas  (fondo {np.median(temp):.1f} C, umbral +{umbral:.1f} C"
                 + (f", {100 * gsd:.1f} cm/pixel" if gsd else ", sin escala") + ")"
                 + ("  AVISO: camara inclinada, sin filtro de tamano; vuela con la camara hacia abajo"
                    if geo and not gsd else ""))

    if len(centros) > 1:
        # con fotos traslapadas, una mancha cortada por el borde sale entera en la foto vecina
        puntos = [p for p in puntos if not p["borde"]]
    puntos = unir_duplicados(puntos, centros, radio_duplicado)
    clasificar(puntos, radio_rebano, minimo_rebano)
    for i, p in enumerate(sorted(puntos, key=lambda p: (p["estado"] == "rebano", -(p["dist_rebano"] or 0))), 1):
        p["id"] = i
        p["fuera_lindero"] = bool(lindero) and not dentro(p["lat"], p["lon"], lindero)
    puntos.sort(key=lambda p: p["id"])
    return puntos, por_foto, sin_geo


# ------------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Rastreo termico de reses aisladas")
    ap.add_argument("--sdk", required=True, help="carpeta con libdirp.dll / libdirp.so del DJI Thermal SDK")
    ap.add_argument("--entrada", required=True, help="foto termica (_T.JPG) o carpeta")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--delta", type=float, default=3.0, help="grados C minimos sobre el fondo")
    ap.add_argument("--radio-rebano", type=float, default=40.0, help="m: separacion maxima dentro del rebano")
    ap.add_argument("--minimo-rebano", type=int, default=5, help="animales minimos para llamarlo rebano")
    ap.add_argument("--radio-duplicado", type=float, default=5.0, help="m: misma res vista en dos fotos")
    ap.add_argument("--lindero", default="", help="KML con el poligono de la finca")
    ap.add_argument("--ancho", type=int, default=3840, help="ancho en pixeles de las imagenes de salida (3840 = 4K; 1920 pesa la cuarta parte)")
    ap.add_argument("--altura", type=float, default=None, help="m sobre el suelo, si la foto no lo trae")
    ap.add_argument("--yaw", type=float, default=None, help="rumbo de la camara, si la foto no lo trae")
    ap.add_argument("--pitch", type=float, default=None, help="inclinacion (-90 = recto abajo)")
    a = ap.parse_args()

    lector = LectorTermico(a.sdk)
    if os.path.isdir(a.entrada):
        fotos = sorted(os.path.join(a.entrada, f) for f in os.listdir(a.entrada) if f.lower().endswith(EXT))
    else:
        fotos = [a.entrada]
    os.makedirs(a.salida, exist_ok=True)
    lindero = leer_lindero(a.lindero) if a.lindero else None

    def leer_todas():
        for ruta in fotos:
            nombre = os.path.basename(ruta)
            datos = open(ruta, "rb").read()
            try:
                temp = lector.leer(datos)
            except ValueError as err:
                print(f"{nombre}: se salta ({err})")
                continue
            meta = leer_metadatos(datos)
            for clave, v in (("altura", a.altura), ("yaw", a.yaw), ("pitch", a.pitch)):
                if v is not None:
                    meta[clave] = v
            yield nombre, temp, meta

    puntos, por_foto, sin_geo = analizar(leer_todas(), delta=a.delta, radio_rebano=a.radio_rebano,
                                         minimo_rebano=a.minimo_rebano, radio_duplicado=a.radio_duplicado,
                                         lindero=lindero)

    for nombre, temp, manchas in por_foto:
        base = os.path.splitext(nombre)[0]
        cv2.imwrite(os.path.join(a.salida, base + "_termica.jpg"),
                    falso_color(temp, manchas, f"{nombre}   {len(manchas)} manchas de calor", ancho_salida=a.ancho),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])

    with open(os.path.join(a.salida, "manchas.csv"), "w", newline="", encoding="utf8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "estado", "lat", "lon", "dist_rebano_m", "fuera_lindero", "animales",
                    "t_max_C", "area_m2", "foto", "google_maps"])
        for p in puntos:
            w.writerow([p["id"], p["estado"], f"{p['lat']:.7f}", f"{p['lon']:.7f}",
                        "" if p["dist_rebano"] is None else f"{p['dist_rebano']:.0f}",
                        "si" if p["fuera_lindero"] else "no", p["animales"], f"{p['t_max']:.1f}",
                        "" if p["area_m2"] is None else f"{p['area_m2']:.2f}", p["foto"],
                        f"https://www.google.com/maps?q={p['lat']:.7f},{p['lon']:.7f}"])
    escribir_kml(puntos, os.path.join(a.salida, "aisladas.kml"))
    dibujar_mapa(puntos, os.path.join(a.salida, "mapa.jpg"))

    ais = [p for p in puntos if p["estado"] != "rebano"]
    print(f"\nAnimales ubicados: {sum(p['animales'] for p in puntos)}  "
          f"en rebano: {sum(p['animales'] for p in puntos if p['estado'] == 'rebano')}  aisladas: {len(ais)}")
    if sin_geo:
        print(f"Manchas sin coordenada (la foto no trae GPS/altura/orientacion): {sin_geo}")
    for p in ais:
        d = "" if p["dist_rebano"] is None else f"  a {p['dist_rebano']:.0f} m del rebano"
        print(f"  #{p['id']}  {p['lat']:.6f}, {p['lon']:.6f}{d}" + ("  FUERA DEL LINDERO" if p["fuera_lindero"] else ""))


if __name__ == "__main__":
    main()
