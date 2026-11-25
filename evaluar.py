"""Mide el error de conteo del modelo en imagenes que no vio al entrenar.

Uso:
  python evaluar.py --modelo modelos/reses_s.onnx --datos RUTA/WAID --split test
  python evaluar.py ... --mosaicos 20     # ademas prueba fotos grandes armadas de 3x3

Para cada umbral de confianza reporta precision, recall, error del total y
error medio por imagen. Una deteccion cuenta como acierto si su caja se
traslapa >= 50 % (IoU) con una res etiquetada.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

from contar import cargar_modelo, detectar

UMBRALES = (0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6)


def leer(datos, split, clase):
    ld = os.path.join(datos, "labels", split)
    items = []
    for f in sorted(os.listdir(ld)):
        cajas = []
        with open(os.path.join(ld, f)) as fh:
            for linea in fh:
                p = linea.split()
                if len(p) == 5 and int(p[0]) == clase:
                    cx, cy, w, h = map(float, p[1:])
                    cajas.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
        if cajas:
            items.append((os.path.join(datos, "images", split, f[:-4] + ".jpg"),
                          np.array(cajas, dtype=np.float32)))
    return items


def emparejar(pred, punt, gt, iou_min=0.5):
    """Devuelve un vector booleano: cada prediccion es acierto o no."""
    ok = np.zeros(len(pred), dtype=bool)
    usado = np.zeros(len(gt), dtype=bool)
    for i in np.argsort(-punt):
        if len(gt) == 0:
            break
        c = pred[i]
        x1 = np.maximum(c[0], gt[:, 0]); y1 = np.maximum(c[1], gt[:, 1])
        x2 = np.minimum(c[2], gt[:, 2]); y2 = np.minimum(c[3], gt[:, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou = inter / ((c[2] - c[0]) * (c[3] - c[1]) +
                       (gt[:, 2] - gt[:, 0]) * (gt[:, 3] - gt[:, 1]) - inter + 1e-9)
        iou[usado] = 0
        j = int(np.argmax(iou))
        if iou[j] >= iou_min:
            ok[i] = True
            usado[j] = True
    return ok


def tabla(resultados, titulo):
    """resultados: lista de (puntajes, aciertos, n_gt) por imagen."""
    print(f"\n{titulo}: {len(resultados)} imagenes, "
          f"{sum(r[2] for r in resultados)} reses etiquetadas")
    print("umbral  precision  recall   total_pred  error_total  error_medio_por_imagen")
    filas = []
    for u in UMBRALES:
        tp = fp = 0
        abs_err = []
        tot_gt = tot_pred = 0
        for punt, ok, n_gt in resultados:
            m = punt >= u
            tp += int(ok[m].sum()); fp += int((~ok[m]).sum())
            tot_gt += n_gt; tot_pred += int(m.sum())
            abs_err.append(abs(int(m.sum()) - n_gt))
        prec = tp / max(1, tp + fp); rec = tp / max(1, tot_gt)
        err = 100.0 * (tot_pred - tot_gt) / tot_gt
        filas.append((u, prec, rec, tot_pred, err, float(np.mean(abs_err))))
        print(f" {u:.2f}    {100 * prec:5.1f}%    {100 * rec:5.1f}%   {tot_pred:7d}     {err:+6.1f}%        {np.mean(abs_err):.2f} reses")
    return filas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", required=True)
    ap.add_argument("--datos", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--clase", type=int, default=1)
    ap.add_argument("--max", type=int, default=0, help="limitar numero de imagenes")
    ap.add_argument("--mosaicos", type=int, default=0)
    ap.add_argument("--guardar", default="", help="carpeta para guardar los mosaicos de prueba")
    ap.add_argument("--hilos", type=int, default=0)
    a = ap.parse_args()

    sesion = cargar_modelo(a.modelo, a.hilos)
    items = leer(a.datos, a.split, a.clase)
    rng = random.Random(1)
    if a.max and a.max < len(items):
        items = rng.sample(items, a.max)

    res = []
    for ruta, gt in items:
        img = cv2.imread(ruta)
        h, w = img.shape[:2]
        gt_px = gt * np.array([w, h, w, h], dtype=np.float32)
        cajas, punt = detectar(sesion, img, conf=min(UMBRALES))
        res.append((punt, emparejar(cajas, punt, gt_px), len(gt_px)))
    tabla(res, f"Imagenes sueltas ({a.split})")

    if a.mosaicos:
        todos = leer(a.datos, a.split, a.clase)
        res = []
        for k in range(a.mosaicos):
            grupo = rng.sample(todos, 9)
            lienzo = np.zeros((1920, 1920, 3), dtype=np.uint8)
            gts = []
            for n, (ruta, gt) in enumerate(grupo):
                img = cv2.imread(ruta)
                if img.shape[:2] != (640, 640):
                    img = cv2.resize(img, (640, 640))
                ox, oy = 640 * (n % 3), 640 * (n // 3)
                lienzo[oy:oy + 640, ox:ox + 640] = img
                gts.append(gt * 640 + np.array([ox, oy, ox, oy], dtype=np.float32))
            gt_px = np.concatenate(gts)
            cajas, punt = detectar(sesion, lienzo, conf=min(UMBRALES))
            res.append((punt, emparejar(cajas, punt, gt_px), len(gt_px)))
            if a.guardar and k < 3:
                os.makedirs(a.guardar, exist_ok=True)
                cv2.imwrite(os.path.join(a.guardar, f"mosaico_{k + 1}.jpg"), lienzo,
                            [cv2.IMWRITE_JPEG_QUALITY, 92])
        tabla(res, "Fotos grandes 1920x1920 (procesadas por mosaicos con traslape)")


if __name__ == "__main__":
    main()
