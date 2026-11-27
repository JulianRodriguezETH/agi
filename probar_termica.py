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


def simular(guardar=""):
    print("3. Vuelo simulado (finca de 400 x 300 m, dron a 60 m, 110 fotos)")
    rng = np.random.default_rng(11)
    LAT0, LON0, ALT, F = 6.95, -71.85, 60.0, 9.1
    W, H = 640, 512
    gsd = T.gsd_nadir(ALT, F)
    # animales: (este, norte, largo, ancho, grados sobre el fondo)
    rebano = []
    while len(rebano) < 40:
        x, y = rng.normal([110, 90], 22, 2)
        if math.hypot(x - 110, y - 90) < 50 and all(math.hypot(x - a[0], y - a[1]) > 3.2 for a in rebano):   # sin tocarse
            rebano.append((x, y, 2.1, 0.8, rng.uniform(6, 10)))
    aisladas = [(335.0, 255.0, 2.1, 0.8, 8.0), (25.0, 270.0, 2.1, 0.8, 7.0),
                (300.0, 45.0, 2.1, 0.8, 8.0), (302.5, 47.0, 1.1, 0.45, 9.0)]  # las dos ultimas: vaca con cria
    animales = [(a, rng.uniform(0, 180)) for a in rebano + aisladas]

    def suelo(E, N):
        """Temperatura del suelo: 24 C con variacion suave, un charco tibio,
        un camino tibio y piedras tibias pequenas (nada de eso es ganado)."""
        t = 24 + 1.2 * np.sin(E / 37.0) * np.cos(N / 51.0)
        t = t + 5.0 * ((((E - 230) / 14.0) ** 2 + ((N - 170) / 9.0) ** 2) < 1)       # charco 28 x 18 m
        t = t + 4.5 * ((np.abs(N - 0.5 * E - 120) < 0.6) & (E > 150) & (E < 260))     # camino de 1.3 m
        for (rx, ry) in ((60, 200), (180, 60), (350, 150), (270, 280)):
            t = t + 6.0 * (np.hypot(E - rx, N - ry) < 0.2)                            # piedras de 40 cm
        return t

    fotos, verdad_px = [], {}
    k = 0
    lineas = np.arange(15, 300, 32)
    for li, N0 in enumerate(lineas):
        xs = np.arange(15, 400, 40)
        yaw = 0.0 if li % 2 == 0 else 180.0       # el dron va y vuelve
        for E0 in (xs if li % 2 == 0 else xs[::-1]):
            k += 1
            ps = math.radians(yaw)
            h = np.array([math.sin(ps), math.cos(ps)]); r = np.array([math.cos(ps), -math.sin(ps)])
            u, v = np.meshgrid(np.arange(W) - W / 2 + 0.5, np.arange(H) - H / 2 + 0.5)
            E = E0 + (u * r[0] - v * h[0]) * gsd
            N = N0 + (u * r[1] - v * h[1]) * gsd
            temp = suelo(E, N).astype(np.float32)
            for (ax, ay, la, an, dt), ang in animales:
                d = np.array([ax - E0, ay - N0])
                pu, pv = W / 2 + d @ r / gsd, H / 2 - d @ h / gsd
                if -40 < pu < W + 40 and -40 < pv < H + 40:
                    capa = np.zeros((H, W), np.float32)
                    cv2.ellipse(capa, ((float(pu), float(pv)), (la / gsd, an / gsd), float(ang - yaw)), 1.0, -1, cv2.LINE_AA)
                    temp = np.maximum(temp, temp + 0) + capa * dt
            temp = cv2.GaussianBlur(temp, (0, 0), 0.8) + rng.normal(0, 0.25, (H, W)).astype(np.float32)
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
        T.dibujar_mapa(puntos, os.path.join(guardar, "mapa_simulado.jpg"))
        T.escribir_kml(puntos, os.path.join(guardar, "aisladas_simulado.kml"))
        for nombre, temp, manchas in por_foto:
            if any(m.get("estado") == "aislada" for m in manchas) or nombre.endswith("_0024_T.JPG"):
                cv2.imwrite(os.path.join(guardar, nombre.replace(".JPG", "_termica.jpg")),
                            T.falso_color(temp, manchas, f"{nombre}   simulated   {len(manchas)} hot spots"))


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
