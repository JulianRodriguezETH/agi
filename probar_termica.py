"""Pruebas del modulo termico. No necesita el SDK de DJI ni fotos.

  python probar_termica.py                 # todas las pruebas
  python probar_termica.py --guardar DIR   # ademas guarda el mapa y fotos del vuelo simulado

1. Geometria: casos con respuesta calculada a mano.
2. Rebano / aisladas / lindero: casos con respuesta conocida.
3. Vuelo simulado: una finca de 400 x 300 m con posiciones conocidas, fotografiada
   en cuadricula como lo haria el dron. Comprueba la cadena completa
   (deteccion, coordenadas, duplicados entre fotos, rebano y aisladas).
   OJO: es una simulacion. Prueba que las cuentas son coherentes, no que la
   camara termica vea reses reales entre el monte.
"""
import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import termica as T

FALLOS = []


def comprobar(nombre, ok, detalle=""):
    print(("  ok    " if ok else "  FALLA ") + nombre + (f"  [{detalle}]" if detalle else ""))
    if not ok:
        FALLOS.append(nombre)


def cerca(a, b, tol):
    return abs(a - b) <= tol


def prueba_geometria():
    print("1. Geometria")
    W, H, F = 640, 512, 9.1
    gsd = T.gsd_nadir(60, F)
    comprobar("escala a 60 m con lente de 9.1 mm = 7.9 cm/pixel", cerca(gsd, 0.0791, 0.0002), f"{100 * gsd:.2f} cm")
    e, n = T.pixel_a_suelo(320, 256, W, H, 60, F, yaw=0, pitch=-90)
    comprobar("centro de la foto = punto bajo el dron", cerca(e, 0, 1e-6) and cerca(n, 0, 1e-6))
    e, n = T.pixel_a_suelo(420, 256, W, H, 60, F, yaw=0, pitch=-90)
    comprobar("100 px a la derecha, rumbo norte -> 7.91 m al este", cerca(e, 7.91, 0.02) and cerca(n, 0, 0.01), f"{e:.2f}, {n:.2f}")
    e, n = T.pixel_a_suelo(320, 156, W, H, 60, F, yaw=0, pitch=-90)
    comprobar("100 px arriba, rumbo norte -> 7.91 m al norte", cerca(n, 7.91, 0.02) and cerca(e, 0, 0.01), f"{e:.2f}, {n:.2f}")
    e, n = T.pixel_a_suelo(420, 256, W, H, 60, F, yaw=90, pitch=-90)
    comprobar("100 px a la derecha, rumbo este -> 7.91 m al sur", cerca(n, -7.91, 0.02) and cerca(e, 0, 0.01), f"{e:.2f}, {n:.2f}")
    e, n = T.pixel_a_suelo(320, 156, W, H, 60, F, yaw=-90, pitch=-90)
    comprobar("100 px arriba, rumbo oeste -> 7.91 m al oeste", cerca(e, -7.91, 0.02) and cerca(n, 0, 0.01), f"{e:.2f}, {n:.2f}")
    e, n = T.pixel_a_suelo(320, 256, W, H, 60, F, yaw=0, pitch=-45)
    comprobar("camara a 45 grados: el centro cae 60 m adelante", cerca(n, 60, 0.01) and cerca(e, 0, 0.01), f"{e:.2f}, {n:.2f}")
    e, n = T.pixel_a_suelo(320, 256, W, H, 60, F, yaw=135, pitch=-30)
    d = 60 / math.tan(math.radians(30))
    comprobar("camara a 30 grados, rumbo sureste: 103.9 m al sureste",
              cerca(e, d * math.sin(math.radians(135)), 0.01) and cerca(n, d * math.cos(math.radians(135)), 0.01), f"{e:.1f}, {n:.1f}")
    comprobar("un pixel sobre el horizonte no toca el suelo", T.pixel_a_suelo(320, 0, W, H, 60, F, 0, -5) is None)
    lat, lon = T.metros_a_latlon(7.0, -71.0, 1000, 1000)
    comprobar("1 km al norte y al este en Arauca (7N, 71W)", cerca(lat, 7.008983, 2e-5) and cerca(lon, -70.990949, 2e-5), f"{lat:.6f}, {lon:.6f}")
    e, n = T.latlon_a_metros(7.0, -71.0, lat, lon)
    comprobar("ida y vuelta metros <-> lat/lon", cerca(e, 1000, 0.01) and cerca(n, 1000, 0.01))


def prueba_rebano():
    print("2. Rebano, aisladas y lindero")
    rng = np.random.default_rng(5)
    pts = [{"e": float(x), "n": float(y), "animales": 1} for x, y in rng.normal([100, 100], 20, (30, 2))]
    pts += [{"e": 400.0, "n": 100.0, "animales": 1},                      # sola, a ~300 m
            {"e": 100.0, "n": 420.0, "animales": 1}, {"e": 103.0, "n": 421.0, "animales": 1}]  # vaca y cria
    T.clasificar(pts, radio=40, minimo_rebano=5)
    comprobar("30 animales juntos = rebano", all(p["estado"] == "rebano" for p in pts[:30]))
    comprobar("la sola y la pareja apartada = 3 aisladas", [p["estado"] for p in pts[30:]] == ["aislada"] * 3)
    comprobar("distancia de la sola al rebano entre 240 y 300 m", 240 < pts[30]["dist_rebano"] < 300, f"{pts[30]['dist_rebano']:.0f} m")
    grupo = [{"e": 0.0, "n": 0.0, "animales": 6}, {"e": 500.0, "n": 0.0, "animales": 1}]
    T.clasificar(grupo, radio=40, minimo_rebano=5)
    comprobar("una mancha que vale por 6 animales cuenta como rebano", grupo[0]["estado"] == "rebano" and grupo[1]["estado"] == "aislada")
    pol = [(7.000, -71.000), (7.000, -70.990), (7.010, -70.990), (7.010, -71.000)]
    comprobar("punto dentro del lindero", T.dentro(7.005, -70.995, pol))
    comprobar("punto fuera del lindero", not T.dentro(7.011, -70.995, pol))


# Una res vista desde arriba: (posicion a lo largo del cuerpo, medio ancho), de la cola al hocico, en fracciones
# del largo y del ancho. Anca, barriga, paleta, cuello y cabeza; las orejas van aparte.
_PERFIL_RES = ((-0.50, 0.00), (-0.485, 0.30), (-0.43, 0.45), (-0.30, 0.50), (-0.10, 0.50), (0.04, 0.47), (0.12, 0.42),
               (0.19, 0.31), (0.25, 0.25), (0.31, 0.25), (0.38, 0.24), (0.44, 0.20), (0.485, 0.14), (0.50, 0.00))

# Una res cebu vista de lado, mirando a la derecha: el contorno completo (x de la cola al hocico, y desde el suelo),
# en fracciones del largo. Giba, papada, cuerno y las cuatro patas.
_SILUETA_LADO = (
    (0.03, 0.50), (0.10, 0.545), (0.30, 0.535), (0.48, 0.525), (0.56, 0.555), (0.62, 0.625), (0.68, 0.635), (0.73, 0.585),
    (0.79, 0.590), (0.845, 0.640), (0.853, 0.725), (0.872, 0.740), (0.882, 0.650), (0.925, 0.625), (0.975, 0.545), (1.00, 0.480),
    (0.985, 0.435), (0.935, 0.435), (0.895, 0.460), (0.870, 0.420), (0.825, 0.330), (0.775, 0.270),
    (0.765, 0.130), (0.775, 0.000), (0.730, 0.000), (0.722, 0.130), (0.705, 0.250),
    (0.675, 0.245), (0.668, 0.140), (0.672, 0.020), (0.630, 0.020), (0.625, 0.140), (0.610, 0.235),
    (0.480, 0.215), (0.350, 0.235), (0.305, 0.265),
    (0.315, 0.140), (0.290, 0.000), (0.245, 0.000), (0.252, 0.150), (0.225, 0.285),
    (0.185, 0.285), (0.195, 0.150), (0.170, 0.020), (0.125, 0.020), (0.128, 0.160), (0.075, 0.330), (0.035, 0.410))
_COLA_LADO = ((0.035, 0.495), (0.005, 0.400), (0.000, 0.230), (0.012, 0.170))
_OREJA_LADO = ((0.835, 0.585), (0.800, 0.520), (0.855, 0.545))


def pintar_res(capa, pu, pv, largo, ancho, grados, mira_atras=False):
    """Suma a 'capa' la silueta caliente de una res (1.0 en el cuerpo, algo menos en orejas y cola), con centro en
    (pu, pv), 'largo' x 'ancho' pixeles y girada 'grados'. Con sub-pixel, para que el borde no salga dentado."""
    th = math.radians(grados + (180.0 if mira_atras else 0.0))
    c, s = math.cos(th), math.sin(th)

    def px(x, y):
        return (pu + (x * c - y * s), pv + (x * s + y * c))

    def poligono(puntos, valor):
        pts = np.round(np.array([px(x * largo, y * ancho) for x, y in puntos]) * 16).astype(np.int32)
        cv2.fillPoly(capa, [pts], valor, cv2.LINE_AA, shift=4)

    cola = np.round(np.array([px(-0.49 * largo, 0.0), px(-0.60 * largo, 0.10 * ancho)]) * 16).astype(np.int32)
    cv2.polylines(capa, [cola], False, 0.45, max(1, int(round(ancho * 0.07))), cv2.LINE_AA, shift=4)
    for lado in (1, -1):                                         # orejas
        poligono([(0.29, lado * 0.15), (0.31, lado * 0.36), (0.36, lado * 0.17)], 0.8)
    arriba = [(x, w) for x, w in _PERFIL_RES]
    abajo = [(x, -w) for x, w in reversed(_PERFIL_RES)]
    poligono(arriba + abajo, 1.0)
    r = int(largo) + 4                                           # el lomo irradia mas que los costados
    y0, y1, x0, x1 = max(0, int(pv) - r), min(capa.shape[0], int(pv) + r), max(0, int(pu) - r), min(capa.shape[1], int(pu) + r)
    if y1 > y0 and x1 > x0:
        trozo = capa[y0:y1, x0:x1]
        dist = cv2.distanceTransform(np.uint8(trozo > 0.5), cv2.DIST_L2, 3)
        trozo *= 0.80 + 0.20 * np.clip(dist / max(0.30 * ancho, 1.0), 0, 1)


def pintar_res_de_lado(capa, x_centro, y_suelo, largo, mira_izquierda=False):
    """Suma a 'capa' la silueta caliente de una res vista de lado, parada en y_suelo: el tronco y la cabeza a 1.0,
    las patas y la cola algo mas frias, como se ven en una camara termica."""
    sx = -1.0 if mira_izquierda else 1.0

    def px(x, y):
        return (x_centro + sx * (x - 0.5) * largo, y_suelo - y * largo)

    def fijo(puntos):
        return np.round(np.array([px(x, y) for x, y in puntos]) * 16).astype(np.int32)

    res = np.zeros_like(capa)
    cv2.fillPoly(res, [fijo(_SILUETA_LADO)], 1.0, cv2.LINE_AA, shift=4)
    cv2.fillPoly(res, [fijo(_OREJA_LADO)], 1.0, cv2.LINE_AA, shift=4)
    filas = np.arange(capa.shape[0], dtype=np.float32)[:, None]
    altura = np.clip((y_suelo - filas) / max(largo, 1.0), 0, 1)                    # 0 en el suelo, ~0.6 en el lomo
    res *= 0.70 + 0.30 * np.clip((altura - 0.05) / 0.22, 0, 1)                     # las patas, mas frias hacia abajo
    dist = cv2.distanceTransform(np.uint8(res > 0.3), cv2.DIST_L2, 3)
    res *= 0.56 + 0.44 * np.clip(dist / (0.12 * largo), 0, 1) ** 0.9               # volumen: el borde irradia menos que el centro
    yy, xx = np.mgrid[0:capa.shape[0], 0:capa.shape[1]].astype(np.float32)

    def foco(x, y, radio, cuanto):                                                 # una zona mas caliente (o mas fria) del cuerpo
        c = px(x, y)
        return 1.0 + cuanto * np.exp(-(((xx - c[0]) ** 2 + (yy - c[1]) ** 2) / (2 * (radio * largo) ** 2)))

    res *= foco(0.93, 0.53, 0.07, 0.22)                                            # la cabeza es lo mas caliente
    res *= foco(0.66, 0.42, 0.10, 0.10) * foco(0.30, 0.42, 0.12, 0.08)             # paleta y anca
    res *= foco(0.47, 0.30, 0.09, -0.10)                                           # la barriga, a la sombra, algo mas fria
    res = np.minimum(res, 1.0)
    cola = np.zeros_like(capa)                                                     # la cola, pegada al anca, mas fria que el cuerpo
    cv2.polylines(cola, [fijo(_COLA_LADO)], False, 0.6, max(1, int(round(largo * 0.016))), cv2.LINE_AA, shift=4)
    np.maximum(res, cola, out=res)
    np.maximum(capa, res, out=capa)


def _ruido_mosaico(rng, lado=512, sigma=4.0):
    """Ruido suave que se repite sin costura, para usarlo de textura del suelo. Media 0, desviacion 1."""
    r = np.tile(rng.normal(0, 1, (lado, lado)).astype(np.float32), (3, 3))
    r = cv2.GaussianBlur(r, (0, 0), sigma)[lado:2 * lado, lado:2 * lado]
    return (r - r.mean()) / (r.std() + 1e-6)


def _muestra(tex, x, y):
    lado = tex.shape[0]
    return cv2.remap(tex, np.mod(x, lado).astype(np.float32), np.mod(y, lado).astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_WRAP)


def toma_oblicua(semilla=21, W=640, H=512):
    """Una toma termica simulada con la camara inclinada: el rebano de lado, en un potrero al amanecer, con pasto, matas,
    una trocha de ganado, un jagueey y la linea de arboles al fondo. Devuelve la temperatura en grados C.
    Solo para mostrar siluetas: la ubicacion en el mapa usa las tomas a plomo. La escena es la misma con cualquier
    sensor (640 x 512 o 1280 x 1024): solo cambia cuanto detalle alcanza a ver."""
    rng = np.random.default_rng(semilla)
    s = W / 640.0
    horizonte = int(H * 0.20)
    v, u = np.mgrid[0:H, 0:W].astype(np.float32)
    foco, h_cam = float(W), 6.5                                                    # camara a 6.5 m, mirando al horizonte
    bajo = np.maximum(v - horizonte, 0.5)
    Z = h_cam * foco / bajo                                                        # metros hacia adelante de cada pixel del suelo
    X = (u - W / 2) * Z / foco                                                     # metros a la derecha
    pisada = Z * Z / (h_cam * foco)                                                # metros de suelo que cubre un pixel (a lo lejos, muchos)
    tex = [_ruido_mosaico(rng) for _ in range(3)]
    temp = 22.4 + 0.9 * np.clip(bajo / (H - horizonte), 0, 1)                      # pasto: algo mas tibio cerca
    for i, (onda, grados) in enumerate(((0.35, 0.30), (1.1, 0.34), (3.5, 0.42), (11.0, 0.50), (36.0, 0.40))):
        nitidez = np.clip((onda / pisada - 1.5) / 2.0, 0, 1)                       # un detalle mas chico que el pixel no se ve
        temp = temp + grados * nitidez * _muestra(tex[i % 3], X * 16 / onda + 91 * i, Z * 16 / onda + 37 * i)
    matas = np.clip((_muestra(tex[1], X * 4.2 + 200, Z * 4.2 + 60) - 1.05) / 0.5, 0, 1)                  # matas y rastrojo, mas frios
    temp = temp - 1.5 * matas * (0.7 + 0.3 * _muestra(tex[0], X * 40, Z * 40)) * np.clip((4.0 / pisada - 1.5) / 2.0, 0, 1)
    trocha = np.abs(X - (2.6 * np.sin(Z / 7.5) + 0.13 * Z - 4.5))                  # la trocha del ganado: tierra pelada, mas tibia
    temp = temp + 1.3 * np.clip(1.0 - trocha / (0.45 + pisada), 0, 1) * np.clip(1.2 - pisada, 0, 1)
    jaguey = ((X + 10.5) / 7.0) ** 2 + ((Z - 31.0) / 4.5) ** 2                     # un jagueey: agua fria y pareja
    agua = np.clip((1.0 - jaguey) * 4, 0, 1)
    temp = temp * (1 - agua) + 21.0 * agua
    cielo = v < horizonte
    temp = np.where(cielo, 20.3 + 0.5 * (v / max(horizonte, 1)), temp).astype(np.float32)                 # cielo frio y parejo
    col = np.arange(W, dtype=np.float32)
    copa = s * (9 + 5 * np.clip(_muestra(tex[2], col[None, :] * 0.7 / s, np.full((1, W), 40.0))[0], -1.6, 1.6)
                + 4 * np.clip(_muestra(tex[0], col[None, :] * 3.0 / s, np.full((1, W), 200.0))[0], -1, 1))                 # la linea de arboles del fondo
    arbol = (v > horizonte - copa[None, :]) & (v < horizonte + 2 * s)
    temp = np.where(arbol, 22.9 + 0.55 * _muestra(tex[1], u * 3.0 / s, v * 3.0 / s) - 0.05 * (horizonte - v) / s, temp).astype(np.float32)
    reses, intentos = [], 0
    while len(reses) < 9 and intentos < 8000:
        intentos += 1
        t = float(rng.uniform(0.08, 1.0)) ** 0.8
        largo = (30 + 112 * t) * s
        x, y = float(rng.uniform(0.06, 0.94) * W), horizonte + 10 * s + (H * 0.97 - horizonte - 10 * s) * t
        libre = all(abs(x - r[0]) > 0.56 * (largo + r[2]) or not (y - 0.80 * largo < r[1] + 6 * s and r[1] - 0.80 * r[2] < y + 6 * s)
                    for r in reses)                                                # sin taparse: cada silueta entera
        if libre and 0.55 * largo < x < W - 0.55 * largo:
            reses.append((x, y, largo, bool(rng.random() < 0.45), float(rng.uniform(7.0, 10.0))))
    for x, y, largo, izq, dt in sorted(reses, key=lambda r: r[1]):                 # primero las del fondo
        capa = np.zeros((H, W), np.float32)
        pintar_res_de_lado(capa, x, y, largo, izq)
        pelo = 1.0 + 0.05 * _muestra(tex[2], (u * 1.3 + x) / s, (v * 1.3 + y) / s)   # el pelaje no irradia parejo
        cubre = np.clip(capa * 3.5, 0, 1)
        temp = np.where(capa > 0.02, temp * (1 - cubre) + (24.6 + capa * pelo * dt) * cubre, temp).astype(np.float32)
    return cv2.GaussianBlur(temp, (0, 0), 0.7) + rng.normal(0, 0.2, (H, W)).astype(np.float32)


def simular(guardar=""):
    print("3. Vuelo simulado (finca de 400 x 300 m, dron a 60 m, 110 fotos)")
    rng = np.random.default_rng(11)
    LAT0, LON0, ALT, F = 6.95, -71.85, 60.0, 9.1
    W, H = 640, 512
    # animales: (este, norte, largo, ancho, grados sobre el fondo)
    rebano = []
    while len(rebano) < 40:
        x, y = rng.normal([110, 90], 22, 2)
        if math.hypot(x - 110, y - 90) < 50 and all(math.hypot(x - a[0], y - a[1]) > 3.2 for a in rebano):   # sin tocarse
            rebano.append((x, y, 2.1, 0.8, rng.uniform(6, 10)))
    aisladas = [(335.0, 255.0, 2.1, 0.8, 8.0), (25.0, 270.0, 2.1, 0.8, 7.0),
                (300.0, 45.0, 2.1, 0.8, 8.0), (302.5, 47.0, 1.1, 0.45, 9.0)]  # las dos ultimas: vaca con cria
    animales = [(a, rng.uniform(0, 180)) for a in rebano + aisladas]

    # el terreno de la finca: pasto con vetas, peladeros tibios, rastrojo, arboles (copas mas frias) y una canada
    rt, PASO_M, BORDE = np.random.default_rng(3), 0.125, 60.0
    tex = [_ruido_mosaico(rt) for _ in range(3)]
    mw, mh = int((400 + 2 * BORDE) / PASO_M), int((300 + 2 * BORDE) / PASO_M)
    copas = np.zeros((mh, mw), np.float32)
    lejos = [(110.0, 90.0, 62.0)] + [(a[0], a[1], 10.0) for a in aisladas]         # sin arboles sobre el rebano ni las aisladas
    for k in range(420):
        if k < 170:                                                                # muchos, a lo largo de la canada
            ae = float(rt.uniform(-BORDE, 400 + BORDE)); an = float(236 - 0.27 * ae + 11 * math.sin(ae / 38.0) + rt.normal(0, 8))
        else:
            ae, an = float(rt.uniform(-BORDE, 400 + BORDE)), float(rt.uniform(-BORDE, 300 + BORDE))
        radio = float(rt.uniform(1.6, 4.6))
        if all(math.hypot(ae - x, an - y) > r + radio for x, y, r in lejos):
            for _ in range(6):                                                     # una copa: varios lobulos
                de, dn = rt.normal(0, radio * 0.38, 2)
                cv2.circle(copas, (int((ae + de + BORDE) / PASO_M), int((an + dn + BORDE) / PASO_M)),
                           int(radio * rt.uniform(0.5, 0.78) / PASO_M), 1.0, -1, cv2.LINE_AA)
    copas = cv2.GaussianBlur(copas, (0, 0), 2.2)

    def suelo(E, N):
        """Temperatura del suelo: 24 C con el pasto, los arboles y la canada, mas un charco tibio,
        un camino tibio y piedras tibias pequenas (nada de eso es ganado)."""
        t = 24 + 1.2 * np.sin(E / 37.0) * np.cos(N / 51.0)
        for i, (onda, grados) in enumerate(((0.18, 0.11), (0.5, 0.15), (1.5, 0.19), (5.0, 0.17), (18.0, 0.18), (60.0, 0.18))):
            t = t + grados * _muestra(tex[i % 3], E * 16 / onda + 53 * i, N * 16 / onda + 29 * i)
        vetas = _muestra(tex[0], (E + 0.6 * N) * 1.1, (N - 0.6 * E) * 9.0)         # el pasto, peinado por el viento
        t = t + 0.14 * vetas
        pelado = np.clip((_muestra(tex[1], E * 1.7 + 300, N * 1.7 + 120) - 1.15) / 0.25, 0, 1)        # peladeros: tierra tibia
        t = t + pelado * (0.55 + 0.12 * _muestra(tex[2], E * 20, N * 20))
        rastrojo = np.clip((_muestra(tex[2], E * 6.0 + 70, N * 6.0 + 410) - 1.45) / 0.3, 0, 1)        # matas: frias y chicas
        t = t - 0.7 * rastrojo
        canada = np.abs(N - (236 - 0.27 * E + 11 * np.sin(E / 38.0)))
        t = t - 0.9 * np.clip(1.0 - canada / 1.5, 0, 1)
        copa = cv2.remap(copas, ((E + BORDE) / PASO_M).astype(np.float32), ((N + BORDE) / PASO_M).astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        t = t - copa * (1.0 + 0.28 * _muestra(tex[1], E * 26, N * 26))
        t = t + 5.0 * ((((E - 230) / 14.0) ** 2 + ((N - 170) / 9.0) ** 2) < 1)       # charco 28 x 18 m
        t = t + 4.5 * ((np.abs(N - 0.5 * E - 120) < 0.6) & (E > 150) & (E < 260))     # camino de 1.3 m
        for (rx, ry) in ((60, 200), (180, 60), (350, 150), (270, 280)):
            t = t + 6.0 * (np.hypot(E - rx, N - ry) < 0.2)                            # piedras de 40 cm
        return t

    def toma(E0, N0, yaw, altura, k=1):
        """La foto termica que tomaria el dron en (E0, N0) a esa altura, mirando recto hacia abajo.
        k=2: el mismo cuadro con un sensor de 1280 x 1024 (como el de una H30T), para las imagenes de muestra."""
        W, H = 640 * k, 512 * k
        g = T.gsd_nadir(altura, F) / k
        ps = math.radians(yaw)
        h = np.array([math.sin(ps), math.cos(ps)]); r = np.array([math.cos(ps), -math.sin(ps)])
        u, v = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5)
        E = E0 + (u * r[0] - v * h[0]) * g
        N = N0 + (u * r[1] - v * h[1]) * g
        temp = suelo(E, N).astype(np.float32)
        margen = 1.5 / g
        for i, ((ax, ay, la, an, dt), ang) in enumerate(animales):
            d = np.array([ax - E0, ay - N0])
            pu, pv = W / 2 + d @ r / g, H / 2 - d @ h / g
            if -margen < pu < W + margen and -margen < pv < H + margen:
                capa = np.zeros((H, W), np.float32)
                pintar_res(capa, float(pu), float(pv), la / g, an / g, float(ang - yaw), mira_atras=i % 2 == 1)
                temp = temp + capa * dt
        return cv2.GaussianBlur(temp, (0, 0), 0.8) + rng.normal(0, 0.25, (H, W)).astype(np.float32)

    fotos, tomas = [], {}
    k = 0
    lineas = np.arange(15, 300, 32)
    for li, N0 in enumerate(lineas):
        xs = np.arange(15, 400, 40)
        yaw = 0.0 if li % 2 == 0 else 180.0       # el dron va y vuelve
        for E0 in (xs if li % 2 == 0 else xs[::-1]):
            k += 1
            temp = toma(E0, N0, yaw, ALT)
            tomas[f"SIM_{k:04d}_T.JPG"] = (E0, N0, yaw)
            # el GPS del dron se equivoca ~1 m
            ge, gn = E0 + rng.normal(0, 1.0), N0 + rng.normal(0, 1.0)
            lat, lon = T.metros_a_latlon(LAT0, LON0, ge, gn)
            fotos.append((f"SIM_{k:04d}_T.JPG", temp,
                          {"lat": lat, "lon": lon, "altura": ALT, "yaw": yaw, "pitch": -90.0, "focal_mm": F}))

    puntos, por_foto, sin_geo = T.analizar(fotos, informar=lambda *_: None)
    o_lat, o_lon = fotos[0][2]["lat"], fotos[0][2]["lon"]
    oe, on = T.latlon_a_metros(LAT0, LON0, o_lat, o_lon)   # origen interno -> coordenadas de la finca
    for p in puntos:
        p["fe"], p["fn"] = p["e"] + oe, p["n"] + on

    n_reb = sum(p["animales"] for p in puntos if p["estado"] == "rebano")
    ais = [p for p in puntos if p["estado"] != "rebano"]
    print(f"     verdad: 40 en rebano, 4 aisladas   |   resultado: {n_reb} en rebano, {len(ais)} aisladas")
    comprobar("rebano contado con error <= 10 %", abs(n_reb - 40) <= 4, f"{n_reb} de 40")
    comprobar("aisladas encontradas = 4", len(ais) == 4, f"{len(ais)}")
    errores = []
    for (ax, ay, *_r) in aisladas:
        d = min((math.hypot(p["fe"] - ax, p["fn"] - ay) for p in ais), default=1e9)
        errores.append(d)
    comprobar("cada aislada ubicada a menos de 5 m de su posicion real (GPS simulado: 1 m de error)", max(errores) < 5.0,
              "errores: " + ", ".join(f"{d:.1f} m" for d in errores))
    falsos = [p for p in puntos if min(math.hypot(p["fe"] - a[0][0], p["fn"] - a[0][1]) for a in animales) > 4]
    comprobar("charco, camino y piedras no se cuentan como animales", len(falsos) == 0, f"{len(falsos)} falsos")
    en_lindero = [(LAT0, LON0)] + [T.metros_a_latlon(LAT0, LON0, x, y) for x, y in ((320, 0), (320, 300), (0, 300))]
    fuera = [p for p in ais if not T.dentro(p["lat"], p["lon"], en_lindero)]
    comprobar("con un lindero que termina a 320 m al este, 1 aislada queda fuera", len(fuera) == 1, f"{len(fuera)}")

    if guardar:
        os.makedirs(guardar, exist_ok=True)
        CALIDAD = [cv2.IMWRITE_JPEG_QUALITY, 86]
        T.dibujar_mapa(puntos, os.path.join(guardar, "mapa_simulado.jpg"))
        T.escribir_kml(puntos, os.path.join(guardar, "aisladas_simulado.kml"))
        # las imagenes de muestra se toman con un sensor de 1280 x 1024: el mismo cuadro, con el doble de detalle.
        # Cada mancha hereda el estado (rebano o aislada) que le dio el analisis del vuelo completo.
        g2 = T.gsd_nadir(ALT, F) / 2
        for nombre, _temp, manchas in por_foto:
            if any(m.get("estado") == "aislada" for m in manchas) or nombre.endswith("_0024_T.JPG"):
                fina = toma(*tomas[nombre], ALT, k=2)
                finas = []
                for m2 in T.detectar_manchas(fina, gsd=g2)[0]:
                    cerca_de = min(manchas, key=lambda m: math.hypot(m["x"] * 2 - m2["x"], m["y"] * 2 - m2["y"]))
                    if math.hypot(cerca_de["x"] * 2 - m2["x"], cerca_de["y"] * 2 - m2["y"]) < 24:
                        m2["estado"] = cerca_de.get("estado")
                        finas.append(m2)
                cv2.imwrite(os.path.join(guardar, nombre.replace(".JPG", "_termica.jpg")),
                            T.falso_color(fina, finas, f"{nombre}   simulated   {len(finas)} hot spots", "ISOLATED"), CALIDAD)
        # una pasada baja (30 m) sobre el rebano, donde la silueta de cada res se distingue bien
        g30 = T.gsd_nadir(30.0, F)
        mejor = max(((sum(1 for (ax, ay, *_r), _a in animales if abs(ax - cx) < W * g30 / 2 - 1.5 and abs(ay - cy) < H * g30 / 2 - 1.5), cx, cy)
                     for cx in np.arange(70, 151, 2.0) for cy in np.arange(50, 131, 2.0)))
        lat, lon = T.metros_a_latlon(LAT0, LON0, mejor[1], mejor[2])
        baja = [("SIM_30M_T.JPG", toma(mejor[1], mejor[2], 0.0, 30.0, k=2),
                 {"lat": lat, "lon": lon, "altura": 30.0, "yaw": 0.0, "pitch": -90.0, "focal_mm": 2 * F})]   # 2F: el pixel mide la mitad
        _p, por_baja, _s = T.analizar(baja, informar=lambda *_: None)
        nombre, temp, manchas = por_baja[0]
        print(f"     pasada baja a 30 m: {mejor[0]} reses en el cuadro, {len(manchas)} manchas")
        cv2.imwrite(os.path.join(guardar, "SIM_30M_T_termica.jpg"),
                    T.falso_color(temp, manchas, f"{nombre}   simulated   30 m   {len(manchas)} hot spots", "ISOLATED"), CALIDAD)
        # y una toma con la camara inclinada, donde se ve la silueta de lado (sin ubicacion: no trae coordenadas)
        obl = T.analizar([("SIM_OBLIQUE_T.JPG", toma_oblicua(W=1280, H=1024), {})], informar=lambda *_: None)[1][0]
        print(f"     toma inclinada: 9 reses en el cuadro, {len(obl[2])} manchas")
        cv2.imwrite(os.path.join(guardar, "SIM_OBLIQUE_T_termica.jpg"),
                    T.falso_color(obl[1], obl[2], f"{obl[0]}   simulated   oblique view   {len(obl[2])} hot spots", "ISOLATED"), CALIDAD)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guardar", default="")
    a = ap.parse_args()
    prueba_geometria()
    prueba_rebano()
    simular(a.guardar)
    print("\nTODO BIEN" if not FALLOS else f"\nFALLARON {len(FALLOS)}: " + "; ".join(FALLOS))
    sys.exit(1 if FALLOS else 0)


if __name__ == "__main__":
    main()
