"""Convierte el modelo entrenado (.pth) a ONNX para usarlo con contar.py.

Uso:
  python exportar.py --yolox RUTA/yolox --pesos modelos/reses_s.pth --salida modelos/reses_s.onnx
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch

from comun import construir


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yolox", required=True)
    ap.add_argument("--pesos", required=True)
    ap.add_argument("--salida", required=True)
    a = ap.parse_args()

    ck = torch.load(a.pesos, map_location="cpu", weights_only=True)
    modelo = construir(ck["variante"], a.yolox)
    modelo.load_state_dict(ck["model"])
    modelo.eval()
    modelo.head.decode_in_inference = True
    x = torch.zeros(1, 3, 640, 640)
    torch.onnx.export(modelo, x, a.salida, input_names=["imagenes"], output_names=["detecciones"],
                      dynamic_axes={"imagenes": {0: "lote"}, "detecciones": {0: "lote"}},
                      opset_version=17, dynamo=False)
    import hashlib
    with open(a.salida, "rb") as fh:                   # AGI compara el modelo con esta huella antes de contar
        huella = hashlib.sha256(fh.read()).hexdigest()
    with open(a.salida + ".sha256", "w", encoding="ascii") as fh:
        fh.write(huella + "  " + os.path.basename(a.salida) + "\n")
    print("exportado:", a.salida, f"{os.path.getsize(a.salida) / 1e6:.1f} MB",
          "(iteraciones de entrenamiento:", ck.get("iter"), ")")


if __name__ == "__main__":
    main()
