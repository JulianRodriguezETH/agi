"""Afinar YOLOX (Apache-2.0) para detectar reses en imagenes aereas.

Uso:
  python entrenar.py --datos RUTA/WAID --yolox RUTA/yolox --pesos yolox_s.pth \
      --variante s --minutos 30 --salida modelos/reses_s.pth

El dataset debe estar en formato YOLO (images/<split>, labels/<split>).
Solo se usa la clase indicada en --clase (1 = cattle en WAID).
El entrenamiento se reparte en el tiempo dado: la tasa de aprendizaje baja
segun el reloj, asi que siempre termina a tiempo. Corre en CPU, CUDA o MPS.
"""
import argparse
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np
import torch

from comun import construir, cargar_coco

MAX_ETIQ = 120


def leer_lista(datos, split, clase):
    """Devuelve [(ruta_imagen, cajas_xyxy_normalizadas)] de imagenes con la clase."""
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


def aumentar(img, cajas, lado, rng):
    """Escala aleatoria, recorte/relleno, giros de 90 grados, espejos y color."""
    h, w = img.shape[:2]
    cajas = cajas * np.array([w, h, w, h], dtype=np.float32)
    s = rng.uniform(0.7, 1.3) * lado / max(h, w)
    nw, nh = max(8, int(round(w * s))), max(8, int(round(h * s)))
    img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    cajas = cajas * s
    lienzo = np.full((lado, lado, 3), 114, dtype=np.uint8)
    ox = rng.randint(0, lado - nw) if nw <= lado else -rng.randint(0, nw - lado)
    oy = rng.randint(0, lado - nh) if nh <= lado else -rng.randint(0, nh - lado)
    sx0, sy0 = max(0, -ox), max(0, -oy)
    dx0, dy0 = max(0, ox), max(0, oy)
    cw, ch = min(nw - sx0, lado - dx0), min(nh - sy0, lado - dy0)
    lienzo[dy0:dy0 + ch, dx0:dx0 + cw] = img[sy0:sy0 + ch, sx0:sx0 + cw]
    area0 = (cajas[:, 2] - cajas[:, 0]) * (cajas[:, 3] - cajas[:, 1])
    cajas = cajas + np.array([ox, oy, ox, oy], dtype=np.float32)
    cajas = np.clip(cajas, 0, lado)
    bw, bh = cajas[:, 2] - cajas[:, 0], cajas[:, 3] - cajas[:, 1]
    ok = (bw >= 4) & (bh >= 4) & (bw * bh >= 0.4 * area0)
    cajas = cajas[ok]
    if rng.random() < 0.5:  # espejo horizontal
        lienzo = lienzo[:, ::-1]
        cajas = np.stack([lado - cajas[:, 2], cajas[:, 1], lado - cajas[:, 0], cajas[:, 3]], 1)
    if rng.random() < 0.5:  # espejo vertical
        lienzo = lienzo[::-1]
        cajas = np.stack([cajas[:, 0], lado - cajas[:, 3], cajas[:, 2], lado - cajas[:, 1]], 1)
    if rng.random() < 0.5:  # transponer (con los espejos cubre los giros de 90)
        lienzo = lienzo.transpose(1, 0, 2)
        cajas = cajas[:, [1, 0, 3, 2]]
    lienzo = np.ascontiguousarray(lienzo)
    hsv = cv2.cvtColor(lienzo, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 0] = (hsv[..., 0] + rng.uniform(-6, 6)) % 180
    hsv[..., 1] = np.clip(hsv[..., 1] * rng.uniform(0.6, 1.4), 0, 255)
    hsv[..., 2] = np.clip(hsv[..., 2] * rng.uniform(0.6, 1.4), 0, 255)
    lienzo = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return lienzo, cajas


def lote(items, idxs, lado, rng):
    xs = np.zeros((len(idxs), 3, lado, lado), dtype=np.float32)
    ts = np.zeros((len(idxs), MAX_ETIQ, 5), dtype=np.float32)
    for b, i in enumerate(idxs):
        ruta, cajas = items[i]
        img = cv2.imread(ruta)
        img, cajas = aumentar(img, cajas, lado, rng)
        xs[b] = img.transpose(2, 0, 1)
        n = min(len(cajas), MAX_ETIQ)
        if n:
            c = cajas[:n]
            ts[b, :n, 1] = (c[:, 0] + c[:, 2]) / 2
            ts[b, :n, 2] = (c[:, 1] + c[:, 3]) / 2
            ts[b, :n, 3] = c[:, 2] - c[:, 0]
            ts[b, :n, 4] = c[:, 3] - c[:, 1]
    return torch.from_numpy(xs), torch.from_numpy(ts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", required=True)
    ap.add_argument("--yolox", required=True)
    ap.add_argument("--pesos", required=True)
    ap.add_argument("--variante", default="s", choices=["nano", "tiny", "s"])
    ap.add_argument("--clase", type=int, default=1)
    ap.add_argument("--minutos", type=float, default=30)
    ap.add_argument("--lote", type=int, default=8)
    ap.add_argument("--lado", type=int, default=640)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--hilos", type=int, default=0)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()

    if a.hilos:
        torch.set_num_threads(a.hilos)
    disp = "cuda" if torch.cuda.is_available() else (
        "mps" if torch.backends.mps.is_available() else "cpu")
    rng = random.Random(0)
    torch.manual_seed(0)

    items = leer_lista(a.datos, "train", a.clase)
    print(f"imagenes de entrenamiento: {len(items)}  dispositivo: {disp}", flush=True)

    modelo = construir(a.variante, a.yolox)
    saltados = cargar_coco(modelo, a.pesos)
    print("capas sin cargar:", saltados, flush=True)
    modelo.to(disp).train()
    ema = construir(a.variante, a.yolox).to(disp)
    ema.load_state_dict(modelo.state_dict())
    for p in ema.parameters():
        p.requires_grad_(False)

    con_decay, sin_decay = [], []
    for n, p in modelo.named_parameters():
        (con_decay if (p.ndim > 1) else sin_decay).append(p)
    opt = torch.optim.SGD([{"params": con_decay, "weight_decay": 5e-4},
                           {"params": sin_decay, "weight_decay": 0.0}],
                          lr=a.lr, momentum=0.9, nesterov=True)

    presupuesto = a.minutos * 60
    t0 = time.time()
    orden, pos, it = [], 0, 0
    perdidas = []
    os.makedirs(os.path.dirname(os.path.abspath(a.salida)), exist_ok=True)

    def guardar():
        torch.save({"model": ema.state_dict(), "variante": a.variante, "iter": it,
                    "imagenes_vistas": it * a.lote}, a.salida)

    while True:
        prog = (time.time() - t0) / presupuesto
        if prog >= 1.0:
            break
        calent = 0.03
        if prog < calent:
            lr = a.lr * (0.1 + 0.9 * prog / calent)
        else:
            lr = a.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * (prog - calent) / (1 - calent))))
        for g in opt.param_groups:
            g["lr"] = lr

        if pos + a.lote > len(orden):
            orden = list(range(len(items)))
            rng.shuffle(orden)
            pos = 0
        idxs = orden[pos:pos + a.lote]
        pos += a.lote
        x, t = lote(items, idxs, a.lado, rng)
        salida = modelo(x.to(disp), t.to(disp))
        perdida = salida["total_loss"]
        opt.zero_grad()
        perdida.backward()
        opt.step()
        it += 1

        d = min(0.99, (1 + it) / (10 + it))
        with torch.no_grad():
            sd = modelo.state_dict()
            for k, v in ema.state_dict().items():
                if v.dtype.is_floating_point:
                    v.mul_(d).add_(sd[k].detach(), alpha=1 - d)
                else:
                    v.copy_(sd[k])

        perdidas.append(float(perdida.detach()))
        if it % 20 == 0:
            print(f"it {it:4d}  {100 * prog:5.1f}%  lr {lr:.5f}  perdida {np.mean(perdidas[-20:]):.3f}  "
                  f"iou {float(salida['iou_loss']):.2f} obj {float(salida['conf_loss']):.2f} "
                  f"cls {float(salida['cls_loss']):.2f}  {(time.time() - t0) / 60:.1f} min", flush=True)
        if it % 100 == 0:
            guardar()

    guardar()
    print(f"FIN  iteraciones {it}  imagenes vistas {it * a.lote}  "
          f"({it * a.lote / len(items):.2f} pasadas)  {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
