# -*- mode: python -*-
# PyInstaller: arma AGI como una carpeta con AGI.exe. Se corre en Windows:
#     python -m PyInstaller agi.spec --noconfirm
# El instalador (instalador/agi.iss) toma esa carpeta.
import os
import re

from PyInstaller.utils.hooks import collect_dynamic_libs

# la version sale de datos.py, para que el .exe y el instalador digan lo mismo que la aplicacion
VERSION = re.search(r'^VERSION = "([^"]+)"', open("datos.py", encoding="utf8").read(), re.M).group(1)
partes = (tuple(int(x) for x in VERSION.split(".")) + (0, 0, 0, 0))[:4]
os.makedirs("build", exist_ok=True)
with open("build/version.txt", "w", encoding="utf8") as fh:
    fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={partes}, prodvers={partes}),
  kids=[StringFileInfo([StringTable("040A04B0", [
    StringStruct("CompanyName", "AGI (open project)"), StringStruct("FileDescription", "AGI - Cattle inventory"),
    StringStruct("FileVersion", "{VERSION}"), StringStruct("ProductName", "AGI"),
    StringStruct("ProductVersion", "{VERSION}"), StringStruct("LegalCopyright", "MIT License")])]),
    VarFileInfo([VarStruct("Translation", [0x040A, 1200])])])
""")

datos = [
    ("modelos/reses_s.onnx", "modelos"),
    ("modelos/reses_s.onnx.sha256", "modelos"),
    ("fuentes/Manrope-Bold.ttf", "fuentes"),
    ("fuentes/Manrope-SemiBold.ttf", "fuentes"),
    ("fuentes/LICENCIA.txt", "fuentes"),
    ("icono/agi.ico", "icono"),
    ("icono/agi_256.png", "icono"),
    ("icono/agi_512.png", "icono"),
]

a = Analysis(
    ["agi.py"],
    pathex=["."],
    binaries=collect_dynamic_libs("onnxruntime"),
    datas=datos,
    hiddenimports=["sqlcipher3", "openpyxl"],
    excludes=["torch", "torchvision", "tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AGI",
    icon="icono/agi.ico",
    console=False,              # sin ventana negra: los errores van a agi_errores.log
    version="build/version.txt",
)
coll = COLLECT(exe, a.binaries, a.datas, name="AGI")
