"""Del video del dron al conteo, sin contar dos veces la misma res.

1. extraer(): recorre uno o varios videos y saca un punto de conteo cada vez que el suelo
   se corrio media imagen (asi no queda potrero sin ver y no se repite de mas). El avance se
   mide con correlacion de fase unas 10 veces por segundo. Si la medida se pierde (un giro,
   una imagen borrosa) se cierra el tramo y se abre otro cuando vuelve.
2. unir(): pone todos los puntos en un mismo plano. Dentro de un tramo, con el avance medido;
   entre tramos o entre videos, comparando las imagenes (rasgos ORB y una transformacion de
   giro, traslado y escala). Lo que no se pueda unir queda en un grupo aparte, y se avisa.
3. numerar(): cada res recibe un numero fijo. Si una res de un punto ya estaba en un punto
   anterior que se traslapa con el, queda marcada como repetida con el numero de la original.
4. mapa(): dibuja el recorrido con cada res contada en su sitio y su numero.
"""
import json
import os

import cv2
import numpy as np

EXT_VIDEO = (".mp4", ".mov", ".m4v", ".avi", ".mkv")
ARCHIVO = "puntos.json"
AVANCE = 0.5            # se saca un punto cuando el suelo se corrio esta fraccion de la imagen
CONF_SEGUIR = 0.08      # respuesta minima de la correlacion de fase para confiar en una medida
MEDIR_HZ = 10           # medidas del avance por segundo de video
BUENAS_PARA_VOLVER = 3  # medidas buenas seguidas para dar por recuperado el seguimiento
INLIERS_MIN = 25        # para aceptar que dos imagenes muestran el mismo suelo
PARECIDO_MIN = 0.25     # correlacion minima entre las dos imagenes en la parte que comparten


def _chico(img, ancho=320):
    h, w = img.shape[:2]
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (ancho, max(8, int(round(ancho * h / w))))).astype(np.float32)


def _corrido(acum, w, h):
    return max(abs(acum[0]) / w, abs(acum[1]) / h)


def extraer(videos, carpeta, avance=None, cancelar=None):
    """Saca los puntos de conteo de los videos, en orden. Devuelve la lista de rutas de imagen.
    Deja en `carpeta` las imagenes y puntos.json con, por punto: video, cuadro, si el avance se
    siguio desde el punto anterior y cuanto se corrio el contenido (dx, dy) desde ese punto."""
    os.makedirs(carpeta, exist_ok=True)
    caps = []
    for v in videos:
        cap = cv2.VideoCapture(v)
        if not cap.isOpened():
            for c in caps:
                c.release()
            cap.release()
            raise ValueError(f"Could not open the video {os.path.basename(v)}. Is it an MP4 or MOV from the drone?")
        caps.append(cap)
    total = sum(int(c.get(cv2.CAP_PROP_FRAME_COUNT) or 0) for c in caps)
    puntos, info_videos, rutas, hecho = [], [], [], 0

    try:
        for k, (video, cap) in enumerate(zip(videos, caps)):
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            medir = max(1, int(round(fps / MEDIR_HZ)))
            base = os.path.splitext(os.path.basename(video))[0]
            i, previo, hann, acum = 0, None, None, [0.0, 0.0]
            perdido, buenas, ultimo_bueno, tam, de_este = False, 0, None, None, 0

            def guardar(img, cuadro, mov, seguido):
                nonlocal de_este
                seg = int(round(cuadro / fps))
                nombre = f"{len(puntos):04d}_v{k + 1}_{seg // 60:02d}m{seg % 60:02d}s_{base}.jpg"
                ok, datos = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                if not ok:
                    return
                ruta = os.path.join(carpeta, nombre)
                datos.tofile(ruta)                         # tofile acepta rutas con tildes en Windows
                puntos.append({"nombre": nombre, "video": k, "cuadro": int(cuadro), "seguido": bool(seguido),
                               "mov": [round(float(mov[0]), 2), round(float(mov[1]), 2)] if mov else None})
                rutas.append(ruta)
                de_este += 1

            while cap.grab():
                if cancelar is not None and cancelar():
                    return rutas
                if i % medir == 0:
                    ok, img = cap.retrieve()
                    if ok and img is not None:
                        h, w = img.shape[:2]
                        tam = [w, h]
                        chico = _chico(img)
                        if previo is None:
                            guardar(img, i, None, False)
                        else:
                            if hann is None or hann.shape != chico.shape:
                                hann = cv2.createHanningWindow((chico.shape[1], chico.shape[0]), cv2.CV_32F)
                            (dx, dy), resp = cv2.phaseCorrelate(previo, chico, hann)
                            if resp < CONF_SEGUIR:                     # se perdio el seguimiento
                                if not perdido and ultimo_bueno is not None and _corrido(ultimo_bueno[2], w, h) >= 0.1:
                                    guardar(ultimo_bueno[0], ultimo_bueno[1], ultimo_bueno[2], True)
                                perdido, buenas, ultimo_bueno = True, 0, None
                            elif perdido:
                                buenas += 1
                                if buenas >= BUENAS_PARA_VOLVER:       # volvio: empieza otro tramo
                                    perdido, acum = False, [0.0, 0.0]
                                    guardar(img, i, None, False)
                            else:
                                acum[0] += dx * w / chico.shape[1]
                                acum[1] += dy * h / chico.shape[0]
                                if _corrido(acum, w, h) >= AVANCE:
                                    guardar(img, i, acum, True)
                                    acum, ultimo_bueno = [0.0, 0.0], None
                                else:
                                    ultimo_bueno = (img, i, list(acum))
                        previo = chico
                i += 1
                if avance is not None and (hecho + i) % 30 == 0:
                    avance(hecho + i, total)
            # el final del video: lo que se alcanzo a ver despues del ultimo punto
            if not perdido and ultimo_bueno is not None and tam and _corrido(ultimo_bueno[2], *tam) >= 0.12:
                guardar(ultimo_bueno[0], ultimo_bueno[1], ultimo_bueno[2], True)
            hecho += i
            info_videos.append({"archivo": os.path.basename(video), "ruta": os.path.abspath(video), "fps": fps,
                                "cuadros": i, "duracion_s": round(i / fps, 1), "tam": tam, "puntos": de_este})
    finally:
        for c in caps:
            c.release()
    if not rutas:
        raise ValueError("The videos have no readable images.")
    with open(os.path.join(carpeta, ARCHIVO), "w", encoding="utf8") as fh:
        json.dump({"version": 2, "videos": info_videos, "puntos": puntos}, fh)
    return rutas


def leer(carpeta):
    try:
        with open(os.path.join(carpeta, ARCHIVO), encoding="utf8") as fh:
            info = json.load(fh)
        return info if info.get("version") == 2 else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------------ union de imagenes

class Rasgos:
    """Rasgos ORB de cada imagen, calculados una vez sobre una copia reducida."""
    ANCHO = 960

    def __init__(self, rutas):
        self.rutas, self.cache = rutas, {}
        self.orb = cv2.ORB_create(2000)
        self.bf = cv2.BFMatcher(cv2.NORM_HAMMING)

    def de(self, i):
        if i not in self.cache:
            img = cv2.imdecode(np.fromfile(self.rutas[i], np.uint8), cv2.IMREAD_GRAYSCALE)
            if img is None:
                self.cache[i] = (None, None, 1.0, None)
            else:
                s = min(1.0, self.ANCHO / img.shape[1])
                chico = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img
                kp, des = self.orb.detectAndCompute(chico, None)
                pts = np.float32([p.pt for p in kp]) / s if kp else None
                self.cache[i] = (pts, des, s, chico)
        return self.cache[i]

    def parecido(self, a, b, A):
        """Correlacion entre la imagen b y la a puesta encima con A, solo donde se traslapan."""
        _, _, s, ga = self.de(a)
        _, _, _, gb = self.de(b)
        S = np.array([[s, 0, 0], [0, s, 0], [0, 0, 1]])
        M = (S @ A @ np.linalg.inv(S))[:2]
        puesta = cv2.warpAffine(ga, M, (gb.shape[1], gb.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
        dentro = cv2.warpAffine(np.ones_like(ga), M, (gb.shape[1], gb.shape[0]), flags=cv2.INTER_NEAREST) > 0
        dentro = cv2.erode(dentro.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if dentro.sum() < 0.03 * dentro.size:
            return 0.0
        x, y = puesta[dentro].astype(np.float32), gb[dentro].astype(np.float32)
        x, y = x - x.mean(), y - y.mean()
        return float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-6))

    def relacion(self, a, b):
        """Transformacion (3x3) que lleva coordenadas de la imagen a a la imagen b, y cuantos rasgos la apoyan."""
        pa, da, s, _ = self.de(a)
        pb, db, _, _ = self.de(b)
        if da is None or db is None or len(da) < 8 or len(db) < 8:
            return None, 0
        pares = self.bf.knnMatch(da, db, k=2)
        buenos = [m for m, *n in pares if n and m.distance < 0.75 * n[0].distance]
        if len(buenos) < INLIERS_MIN:
            return None, 0
        src = pa[[m.queryIdx for m in buenos]]
        dst = pb[[m.trainIdx for m in buenos]]
        A, mask = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0 / s,
                                              maxIters=4000, confidence=0.995)
        if A is None:
            return None, 0
        inl = int(mask.sum())
        escala = float(np.hypot(A[0, 0], A[1, 0]))
        if inl < INLIERS_MIN or inl < 0.25 * len(buenos) or not 0.85 <= escala <= 1.18:
            return None, inl
        A3 = np.vstack([A, [0, 0, 1]])
        if self.parecido(a, b, A3) < PARECIDO_MIN:          # los rasgos coinciden pero el suelo no se parece
            return None, inl
        return A3, inl


def _T(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1]], dtype=np.float64)


def _esquinas(tam):
    w, h = tam
    return np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)


def _aplicar(M, pts):
    pts = np.asarray(pts, dtype=np.float64)
    return pts @ M[:2, :2].T + M[:2, 2]


def _traslape(Ma_b, tam_a, tam_b):
    """Fraccion de la imagen b que cubre la imagen a, puesta en b con Ma_b."""
    poli = _aplicar(Ma_b, _esquinas(tam_a)).astype(np.float32)
    area, _ = cv2.intersectConvexConvex(poli, _esquinas(tam_b).astype(np.float32))
    return float(area) / (tam_b[0] * tam_b[1])


def unir(rutas, info, avance=None):
    """Pone cada punto en el plano de su grupo. Devuelve {"G": [3x3 por punto], "grupo": [...],
    "rel": {(i, q): 3x3}} donde rel guarda las relaciones medidas con imagen entre puntos que se traslapan."""
    puntos, videos = info["puntos"], info["videos"]
    tam = [videos[p["video"]]["tam"] for p in puntos]
    rasgos = Rasgos(rutas)
    n = len(puntos)
    G, grupo, rel, grupos = [None] * n, [None] * n, {}, 0
    for i, p in enumerate(puntos):
        if avance is not None:
            avance(i, n)
        ant = puntos[i - 1] if i else None
        if ant is not None and ant["video"] == p["video"]:
            # con el punto anterior del mismo video: primero por imagen, que tambien ve los giros;
            # si el suelo no tiene rasgos, con el avance medido en el camino
            A, _ = rasgos.relacion(i, i - 1)
            if A is not None:
                G[i], grupo[i] = G[i - 1] @ A, grupo[i - 1]
                rel[(i, i - 1)] = A
                continue
            if p["seguido"] and p["mov"] is not None:
                G[i], grupo[i] = G[i - 1] @ _T(-p["mov"][0], -p["mov"][1]), grupo[i - 1]
                continue
        mejor = (None, 0, None)
        for q in reversed(range(i)):                 # primero los mas cercanos en el tiempo
            A, inl = rasgos.relacion(i, q)
            if A is not None and inl > mejor[1]:
                mejor = (A, inl, q)
                if inl >= 120:
                    break
        if mejor[0] is not None:
            A, _, q = mejor
            G[i], grupo[i] = G[q] @ A, grupo[q]
            rel[(i, q)] = A
        else:
            G[i], grupo[i] = np.eye(3), grupos
            grupos += 1
    # relaciones finas entre puntos que se traslapan y no son vecinos seguidos (por ejemplo, lineas vecinas)
    for i in range(n):
        for q in range(i):
            if grupo[q] != grupo[i] or (i, q) in rel:
                continue
            if q == i - 1 and puntos[i]["seguido"] and puntos[i]["video"] == puntos[q]["video"]:
                continue
            R = np.linalg.inv(G[q]) @ G[i]
            if _traslape(R, tam[i], tam[q]) < 0.05:
                continue
            A, _ = rasgos.relacion(i, q)
            if A is not None:
                rel[(i, q)] = A
    return {"G": G, "grupo": grupo, "rel": rel, "grupos": len(set(grupo)), "tam": tam}


def guardar_union(carpeta, u):
    info = leer(carpeta)
    info["union"] = {"G": [np.asarray(m).round(6).tolist() for m in u["G"]], "grupo": [int(g) for g in u["grupo"]],
                     "rel": [[int(i), int(q), np.asarray(m).round(6).tolist()] for (i, q), m in u["rel"].items()],
                     "grupos": int(u["grupos"]), "tam": u["tam"]}
    with open(os.path.join(carpeta, ARCHIVO), "w", encoding="utf8") as fh:
        json.dump(info, fh)


def leer_union(info):
    u = info.get("union")
    if not u:
        return None
    return {"G": [np.array(m) for m in u["G"]], "grupo": u["grupo"], "grupos": u["grupos"], "tam": u["tam"],
            "rel": {(i, q): np.array(m) for i, q, m in u["rel"]}}


# ------------------------------------------------------------------ numeros fijos

def _cuenta(d, umbral):
    return not d.get("quitada") and (d["origen"] == "manual" or d["conf"] >= umbral)


def numerar(dets_por_punto, union, umbral, puntos=None):
    """Le pone a cada res un numero fijo ("id") y marca "repetida" la que ya se habia visto en un punto
    anterior que se traslapa. Lo agregado a mano nunca se marca repetido. Devuelve cuantas reses hay."""
    n = len(dets_por_punto)
    siguiente = 1
    for i, dets in enumerate(dets_por_punto):
        for d in dets:
            d.pop("id", None)
            d["repetida"] = False
        if union is None:
            for d in dets:
                if _cuenta(d, umbral):
                    d["id"] = siguiente
                    siguiente += 1
            continue
        G, grupo, rel, tam = union["G"], union["grupo"], union["rel"], union["tam"]
        pares = []
        for q in range(i):
            if grupo[q] != grupo[i]:
                continue
            if (i, q) in rel:
                R = rel[(i, q)]
            elif q == i - 1 and puntos and puntos[i]["seguido"] and puntos[i]["mov"] and puntos[i]["video"] == puntos[q]["video"]:
                R = _T(-puntos[i]["mov"][0], -puntos[i]["mov"][1])
            else:
                R = np.linalg.inv(G[q]) @ G[i]
                if _traslape(R, tam[i], tam[q]) < 0.05:
                    continue
            viejas = [d for d in dets_por_punto[q] if "id" in d]
            if not viejas:
                continue
            w, h = tam[q]
            for j, d in enumerate(dets):
                if d["origen"] != "ia" or not _cuenta(d, umbral):
                    continue
                x1, y1, x2, y2 = d["caja"]
                cx, cy = _aplicar(R, [[(x1 + x2) / 2, (y1 + y2) / 2]])[0]
                if not (-0.05 * w <= cx <= 1.05 * w and -0.05 * h <= cy <= 1.05 * h):
                    continue                                    # ese pedazo no se veia en el punto q
                for v in viejas:
                    a1, b1, a2, b2 = v["caja"]
                    lado = max(x2 - x1, y2 - y1, a2 - a1, b2 - b1)
                    dist = float(np.hypot(cx - (a1 + a2) / 2, cy - (b1 + b2) / 2))
                    if dist <= 0.6 * lado:
                        pares.append((dist, j, v["id"]))
        usadas_j, usadas_id = set(), set()
        for dist, j, ident in sorted(pares):                    # cada res de antes explica a lo sumo una de ahora
            if j not in usadas_j and ident not in usadas_id:
                usadas_j.add(j)
                usadas_id.add(ident)
                dets[j]["repetida"] = True
                dets[j]["id"] = ident
        for j, d in enumerate(dets):
            if _cuenta(d, umbral) and j not in usadas_j:
                d["id"] = siguiente
                siguiente += 1
    return siguiente - 1


# ------------------------------------------------------------------ mapa

def mapa(rutas, union, dets_por_punto, umbral, ancho_max=1400):
    """Dibuja cada grupo del recorrido con las imagenes en su sitio y cada res contada con su numero.
    Devuelve una lista de imagenes BGR, una por grupo (normalmente una sola)."""
    G, grupo, tam = union["G"], union["grupo"], union["tam"]
    salida = []
    for g in sorted(set(grupo)):
        idx = [i for i in range(len(rutas)) if grupo[i] == g]
        todas = np.vstack([_aplicar(G[i], _esquinas(tam[i])) for i in idx])
        x0, y0 = todas.min(axis=0)
        x1, y1 = todas.max(axis=0)
        s = min(1.0, ancho_max / max(1.0, x1 - x0), ancho_max / max(1.0, y1 - y0))
        W, H = int(np.ceil((x1 - x0) * s)) + 1, int(np.ceil((y1 - y0) * s)) + 1
        lienzo = np.full((H, W, 3), 40, np.uint8)
        A0 = np.array([[s, 0, -x0 * s], [0, s, -y0 * s], [0, 0, 1]])
        for i in idx:
            img = cv2.imdecode(np.fromfile(rutas[i], np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                continue
            M = (A0 @ G[i])[:2]
            mascara = cv2.warpAffine(np.full(img.shape[:2], 255, np.uint8), M, (W, H), flags=cv2.INTER_NEAREST)
            pegada = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_AREA)
            lienzo[mascara > 0] = pegada[mascara > 0]
        for i in idx:                                            # borde de cada imagen: lo que se alcanzo a ver
            borde = _aplicar(A0 @ G[i], _esquinas(tam[i])).astype(np.int32)
            cv2.polylines(lienzo, [borde], True, (235, 235, 235), 1, cv2.LINE_AA)
        r = max(6, int(round(11 * max(1.0, W / 1000))))
        letra = max(0.4, 0.45 * r / 9)
        for i in idx:
            for d in dets_por_punto[i]:
                if "id" not in d or d.get("repetida") or not _cuenta(d, umbral):
                    continue
                x1d, y1d, x2d, y2d = d["caja"]
                cx, cy = _aplicar(A0 @ G[i], [[(x1d + x2d) / 2, (y1d + y2d) / 2]])[0]
                color = (255, 200, 0) if d["origen"] == "manual" else (10, 214, 255)
                cv2.circle(lienzo, (int(cx), int(cy)), r, color, -1, cv2.LINE_AA)
                cv2.circle(lienzo, (int(cx), int(cy)), r, (20, 19, 20), 1, cv2.LINE_AA)
                texto = str(d["id"])
                (tw, th), _ = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, letra, 1)
                cv2.putText(lienzo, texto, (int(cx - tw / 2), int(cy + th / 2)), cv2.FONT_HERSHEY_SIMPLEX, letra,
                            (20, 19, 20), 1, cv2.LINE_AA)
        salida.append(lienzo)
    return salida


def mapa_unico(rutas, union, dets_por_punto, umbral, ancho_max=1400):
    """Todos los grupos en una sola imagen, uno debajo del otro, con una franja que los separa."""
    partes = mapa(rutas, union, dets_por_punto, umbral, ancho_max)
    if len(partes) == 1:
        return partes[0]
    ancho = max(p.shape[1] for p in partes)
    filas = []
    for k, p in enumerate(partes, 1):
        franja = np.full((44, ancho, 3), 255, np.uint8)
        cv2.putText(franja, f"Part {k} of {len(partes)} (could not be joined to the others)", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (20, 19, 20), 2, cv2.LINE_AA)
        filas += [franja, cv2.copyMakeBorder(p, 0, 0, 0, ancho - p.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))]
    return np.vstack(filas)
