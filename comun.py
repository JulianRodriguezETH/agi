"""Utilidades compartidas: construir YOLOX (Apache-2.0) y preparar imagenes."""
import sys
import numpy as np
import torch
import torch.nn as nn

VARIANTES = {"nano": (0.33, 0.25, True), "tiny": (0.33, 0.375, False), "s": (0.33, 0.50, False)}
COCO_VACA = 19  # indice de "cow" en las 80 clases de COCO


def construir(variante, yolox_dir, num_clases=1):
    if yolox_dir not in sys.path:
        sys.path.insert(0, yolox_dir)
    from yolox.models import YOLOX, YOLOPAFPN, YOLOXHead
    prof, ancho, dw = VARIANTES[variante]
    canales = [256, 512, 1024]
    backbone = YOLOPAFPN(prof, ancho, in_channels=canales, act="silu", depthwise=dw)
    cabeza = YOLOXHead(num_clases, ancho, in_channels=canales, act="silu", depthwise=dw)
    modelo = YOLOX(backbone, cabeza)
    for m in modelo.modules():
        if isinstance(m, nn.BatchNorm2d):
            m.eps = 1e-3
            m.momentum = 0.03
    modelo.head.initialize_biases(1e-2)
    return modelo


def cargar_coco(modelo, ruta):
    """Carga pesos preentrenados en COCO; la salida de clase arranca desde 'cow'."""
    ck = torch.load(ruta, map_location="cpu", weights_only=True)
    sd = ck["model"] if "model" in ck else ck
    propio = modelo.state_dict()
    nuevos, saltados = {}, []
    for k, v in sd.items():
        if k not in propio:
            saltados.append(k)
            continue
        if v.shape == propio[k].shape:
            nuevos[k] = v
        elif "cls_preds" in k and v.shape[0] == 80 and propio[k].shape[0] == 1:
            nuevos[k] = v[COCO_VACA:COCO_VACA + 1].clone()
        else:
            saltados.append(k)
    modelo.load_state_dict(nuevos, strict=False)
    return saltados


def letterbox(img, lado, relleno=114):
    """Escala manteniendo proporcion y rellena arriba-izquierda (convencion YOLOX)."""
    import cv2
    h, w = img.shape[:2]
    r = min(lado / h, lado / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    if (nh, nw) != (h, w):
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    lienzo = np.full((lado, lado, 3), relleno, dtype=np.uint8)
    lienzo[:nh, :nw] = img
    return lienzo, r
