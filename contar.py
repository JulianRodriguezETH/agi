"""Conteo de reses en fotos aereas. Solo necesita: onnxruntime, opencv-python, numpy.

Uso:
  python contar.py --modelo modelos/reses_s.onnx --entrada fotos/ --salida resultados/

Por cada foto escribe:
  <nombre>_count.jpg    la foto con cada res en un cuadro numerado (#1, #2, ...)
  <nombre>_cattle.csv   una fila por res: numero, caja en pixeles y confianza
y un summary.csv con el total por foto.

Las fotos grandes se procesan por mosaicos de 640 px con traslape, y las
detecciones repetidas en el traslape se unen para no contar dos veces.

OJO: el total de una carpeta es la suma por foto. Si las fotos del vuelo se
traslapan entre si, la misma res aparece en varias; unir eso necesita el GPS
de cada foto y es la siguiente fase.
"""
import argparse
import csv
import os
import sys

import cv2
import numpy as np
import onnxruntime as ort

LADO = 640
EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp")


def cargar_modelo(ruta, hilos=0):
    op = ort.SessionOptions()
    if hilos:
        op.intra_op_num_threads = hilos
    disponibles = ort.get_available_providers()
    prov = [p for p in ("CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
            if p in disponibles]
    return ort.InferenceSession(ruta, sess_options=op, providers=prov)


def _posiciones(total, lado, paso):
    if total <= lado:
        return [0]
    return list(range(0, total - lado, paso)) + [total - lado]


def _iou_ios(c, resto):
    x1 = np.maximum(c[0], resto[:, 0]); y1 = np.maximum(c[1], resto[:, 1])
    x2 = np.minimum(c[2], resto[:, 2]); y2 = np.minimum(c[3], resto[:, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    a = (c[2] - c[0]) * (c[3] - c[1])
    b = (resto[:, 2] - resto[:, 0]) * (resto[:, 3] - resto[:, 1])
    return inter / (a + b - inter + 1e-9), inter / (np.minimum(a, b) + 1e-9)


def unir(cajas, punt, cortada, iou_max=0.5, ios_max=0.6):
    """Supresion de duplicados. Las cajas completas mandan sobre las cortadas
    por el borde de un mosaico; una caja cortada tambien se descarta si queda
    casi toda dentro de otra (es la misma res vista a medias)."""
    if len(cajas) == 0:
        return np.zeros(0, dtype=int)
    orden = np.lexsort((-punt, cortada))  # primero no cortadas, luego por puntaje
    vivas = np.ones(len(cajas), dtype=bool)
    quedan = []
    for pos, i in enumerate(orden):
        if not vivas[i]:
            continue
        quedan.append(i)
        resto = orden[pos + 1:]
        resto = resto[vivas[resto]]
        if len(resto) == 0:
            continue
        iou, ios = _iou_ios(cajas[i], cajas[resto])
        fuera = (iou > iou_max) | ((ios > ios_max) & (cortada[resto] | cortada[i]))
        vivas[resto[fuera]] = False
    return np.array(quedan, dtype=int)


def detectar(sesion, img, conf=0.30, escala=1.0, solape=0.25, lote=4):
    """Devuelve (cajas Nx4 en pixeles de la foto original, puntajes N)."""
    if escala != 1.0:
        img = cv2.resize(img, None, fx=escala, fy=escala,
                         interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_LINEAR)
    alto, ancho = img.shape[:2]
    paso = int(LADO * (1 - solape))
    origenes = [(x, y) for y in _posiciones(alto, LADO, paso) for x in _posiciones(ancho, LADO, paso)]
    entrada = sesion.get_inputs()[0].name
    cajas, punt, cortada = [], [], []
    for k in range(0, len(origenes), lote):
        grupo = origenes[k:k + lote]
        x = np.full((len(grupo), 3, LADO, LADO), 114, dtype=np.float32)
        for b, (ox, oy) in enumerate(grupo):
            rec = img[oy:oy + LADO, ox:ox + LADO]
            x[b, :, :rec.shape[0], :rec.shape[1]] = rec.transpose(2, 0, 1)
        sal = sesion.run(None, {entrada: x})[0]  # [lote, 8400, 6] = cx, cy, w, h, obj, cls
        for b, (ox, oy) in enumerate(grupo):
            p = sal[b]
            s = p[:, 4] * p[:, 5]
            m = s >= conf
            if not m.any():
                continue
            p, s = p[m], s[m]
            c = np.stack([p[:, 0] - p[:, 2] / 2, p[:, 1] - p[:, 3] / 2,
                          p[:, 0] + p[:, 2] / 2, p[:, 1] + p[:, 3] / 2], 1)
            # caja "cortada": toca un borde del mosaico que no es borde de la foto
            corta = (((c[:, 0] <= 2) & (ox > 0)) | ((c[:, 1] <= 2) & (oy > 0)) |
                     ((c[:, 2] >= LADO - 2) & (ox + LADO < ancho)) |
                     ((c[:, 3] >= LADO - 2) & (oy + LADO < alto)))
            c = c + np.array([ox, oy, ox, oy], dtype=np.float32)
            c[:, [0, 2]] = np.clip(c[:, [0, 2]], 0, ancho)
            c[:, [1, 3]] = np.clip(c[:, [1, 3]], 0, alto)
            cajas.append(c); punt.append(s); cortada.append(corta)
    if not cajas:
        return np.zeros((0, 4), dtype=np.float32), np.zeros(0, dtype=np.float32)
    cajas, punt, cortada = np.concatenate(cajas), np.concatenate(punt), np.concatenate(cortada)
    q = unir(cajas, punt, cortada)
    return cajas[q] / escala, punt[q]


def ordenar(cajas):
    """Orden de lectura: por franjas de arriba abajo y de izquierda a derecha."""
    if len(cajas) == 0:
        return np.zeros(0, dtype=int)
    cy = (cajas[:, 1] + cajas[:, 3]) / 2
    cx = (cajas[:, 0] + cajas[:, 2]) / 2
    franja = max(8.0, 2.0 * float(np.median(cajas[:, 3] - cajas[:, 1])))
    return np.lexsort((cx, np.floor(cy / franja)))


def dibujar(img, cajas, titulo, colores=None, etiquetas=None, punteadas=()):
    """colores: lista opcional con un color BGR por caja (por defecto azul). etiquetas: el numero de cada
    caja (por defecto 1, 2, 3...). punteadas: cajas de reses ya contadas antes, en linea blanca y sin numero."""
    out = img.copy()
    alto, ancho = out.shape[:2]
    g = max(1, int(round(max(alto, ancho) / 1300)))
    fe = max(0.4, max(alto, ancho) / 3200)
    for c in punteadas:
        x1, y1, x2, y2 = [int(round(v)) for v in c]
        for a, b in (((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))):
            largo = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
            for k in range(0, largo, 8):
                p = (a[0] + (b[0] - a[0]) * k // max(largo, 1), a[1] + (b[1] - a[1]) * k // max(largo, 1))
                q = (a[0] + (b[0] - a[0]) * min(k + 4, largo) // max(largo, 1), a[1] + (b[1] - a[1]) * min(k + 4, largo) // max(largo, 1))
                cv2.line(out, p, q, (255, 255, 255), g, cv2.LINE_AA)
    for n, c in enumerate(cajas, 1):
        color = colores[n - 1] if colores else (255, 165, 90)
        x1, y1, x2, y2 = [int(round(v)) for v in c]
        cv2.rectangle(out, (x1, y1), (x2, y2), color, g)
        txt = f"#{etiquetas[n - 1] if etiquetas else n}"
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, fe, g)
        ty = y1 - 3 if y1 - th - 4 > 0 else y2 + th + 3
        cv2.rectangle(out, (x1, ty - th - 2), (x1 + tw + 2, ty + 2), color, -1)
        cv2.putText(out, txt, (x1 + 1, ty), cv2.FONT_HERSHEY_SIMPLEX, fe, (0, 0, 0), g, cv2.LINE_AA)
    if not titulo:
        return out
    # el total va en una franja encima de la foto, para no tapar ninguna res
    fe2 = fe * 1.6
    (tw, th), _ = cv2.getTextSize(titulo, cv2.FONT_HERSHEY_SIMPLEX, fe2, g + 1)
    franja = np.zeros((th + 20, ancho, 3), dtype=np.uint8)
    cv2.putText(franja, titulo, (8, th + 9), cv2.FONT_HERSHEY_SIMPLEX, fe2, (255, 255, 255), g + 1, cv2.LINE_AA)
    return np.vstack([franja, out])


def main():
    ap = argparse.ArgumentParser(description="Cattle counting in aerial photos")
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--entrada", required=True, help="photo or folder of photos")
    ap.add_argument("--salida", required=True, help="results folder")
    ap.add_argument("--conf", type=float, default=0.30, help="minimum confidence")
    ap.add_argument("--escala", type=float, default=1.0,
                    help="factor to rescale the photo; aim for an animal to measure 30-60 px")
    ap.add_argument("--hilos", type=int, default=0)
    a = ap.parse_args()

    sesion = cargar_modelo(a.modelo, a.hilos)
    if os.path.isdir(a.entrada):
        fotos = sorted(os.path.join(a.entrada, f) for f in os.listdir(a.entrada)
                       if f.lower().endswith(EXT))
    else:
        fotos = [a.entrada]
    if not fotos:
        sys.exit("No photos in " + a.entrada)
    os.makedirs(a.salida, exist_ok=True)

    resumen = []
    for ruta in fotos:
        img = cv2.imread(ruta)
        if img is None:
            print("could not read:", ruta)
            continue
        cajas, punt = detectar(sesion, img, conf=a.conf, escala=a.escala)
        o = ordenar(cajas)
        cajas, punt = cajas[o], punt[o]
        base = os.path.splitext(os.path.basename(ruta))[0]
        cv2.imwrite(os.path.join(a.salida, base + "_count.jpg"),
                    dibujar(img, cajas, f"TOTAL: {len(cajas)} cattle"),
                    [cv2.IMWRITE_JPEG_QUALITY, 90])
        with open(os.path.join(a.salida, base + "_cattle.csv"), "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["animal", "x1", "y1", "x2", "y2", "confidence"])
            for n, (c, s) in enumerate(zip(cajas, punt), 1):
                w.writerow([n] + [int(round(v)) for v in c] + [f"{s:.2f}"])
        resumen.append((os.path.basename(ruta), len(cajas)))
        print(f"{os.path.basename(ruta)}: {len(cajas)} cattle")

    with open(os.path.join(a.salida, "summary.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["photo", "cattle"])
        w.writerows(resumen)
    print(f"Photos: {len(resumen)}  total cattle: {sum(n for _, n in resumen)}")


if __name__ == "__main__":
    main()
