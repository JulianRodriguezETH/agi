"""Imprime la version de AGI (la de datos.py) para el instalador, sin importar nada pesado."""
import os
import re

AQUI = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(AQUI, "..", "datos.py"), encoding="utf8") as fh:
    print(re.search(r'^VERSION = "([^"]+)"', fh.read(), re.M).group(1))
