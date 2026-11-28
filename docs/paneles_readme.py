"""Dibuja los paneles del README (docs/readme/): cabecera, pasos, cifras, pilares y botones.

  python docs/paneles_readme.py .

Los textos y cifras de los paneles estan en este archivo: si cambian en el README, se cambian aqui y se vuelve a correr.
Necesita playwright (pip install playwright) y Google Chrome; solo hace falta para rehacer las imagenes.
"""
import base64, os, sys
from playwright.sync_api import sync_playwright
R = os.path.abspath(sys.argv[1]); SAL = os.path.join(R, "docs", "readme"); os.makedirs(SAL, exist_ok=True)
b64 = lambda ruta: base64.b64encode(open(ruta, "rb").read()).decode()
F6, F7 = b64(f"{R}/fuentes/Manrope-SemiBold.ttf"), b64(f"{R}/fuentes/Manrope-Bold.ttf")
LOGO = b64(f"{R}/icono/agi_logo_oscuro.png"); TERM = b64(f"{R}/ejemplos_termica/SIM_OBLIQUE_T_termica.jpg")
CSS = f"""
@font-face {{ font-family: Manrope; font-weight: 600; src: url(data:font/ttf;base64,{F6}); }}
@font-face {{ font-family: Manrope; font-weight: 700; src: url(data:font/ttf;base64,{F7}); }}
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ background: transparent; }}
body {{ width: 880px; font-family: Inter, "Segoe UI", sans-serif; color: #fff; -webkit-font-smoothing: antialiased; }}
.panel {{ width: 880px; background: #000; border-radius: 20px; overflow: hidden; }}
h1, h2, h3, .num {{ font-family: Manrope, sans-serif; font-weight: 600; }}
.sub {{ color: rgba(255,255,255,.65); }}
.grad {{ background: linear-gradient(153deg, #f6f4f0 0%, #d9d3c9 100%); border-radius: 16px; color: #141414; }}
.grad .sub {{ color: rgba(20,20,20,.62); }}
.soft {{ background: linear-gradient(153deg, rgba(230,223,211,.16) 0%, rgba(230,223,211,0) 100%), #0d0c0b; border: 1px solid rgba(255,255,255,.1); border-radius: 16px; }}
.pill {{ display: inline-flex; align-items: center; gap: 8px; height: 38px; padding: 0 20px; border-radius: 999px; background: #1a1a1a;
        border: 1px solid #333; font-size: 14px; font-weight: 500; color: #fff; white-space: nowrap; }}
.pill.blanca {{ background: #fff; border-color: #fff; color: #0a0a0a; font-weight: 600; }}
"""
def pagina(cuerpo): return f"<!doctype html><html><head><meta charset='utf8'><style>{CSS}</style></head><body>{cuerpo}</body></html>"

HERO = f"""<div class="panel" id="x" style="padding:0 0 46px">
  <div style="display:flex;align-items:center;justify-content:space-between;height:56px;padding:0 26px;background:#141414">
    <img src="data:image/png;base64,{LOGO}" style="height:52px;margin-left:-14px">
    <span class="sub" style="font-size:13px">Open portfolio project · MIT</span></div>
  <div style="position:relative;height:400px;overflow:hidden">
    <img src="data:image/jpeg;base64,{TERM}" style="position:absolute;left:0;top:-128px;width:880px">
    <div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,0) 40%,#000 96%),linear-gradient(90deg,#000 0%,rgba(0,0,0,0) 12%,rgba(0,0,0,0) 84%,#000 96%)"></div>
    <span style="position:absolute;right:26px;top:18px;font-size:11.5px;color:rgba(255,255,255,.6);background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.14);border-radius:999px;padding:5px 12px">Simulated thermal frame · experimental module</span></div>
  <h1 style="font-size:44px;line-height:1.14;text-align:center;letter-spacing:-.5px;margin-top:-46px;position:relative">Cattle counting<br>from drone video</h1>
  <p class="sub" style="font-size:16px;line-height:1.55;text-align:center;max-width:620px;margin:18px auto 0">Counts every animal once, keeps a person in the loop to review
  each count, and issues digitally signed PDF reports from an encrypted local database.</p></div>"""

pasos = [("Video in", "A count point every time the drone advances half a frame"), ("Detect", "YOLOX-s on ONNX Runtime, on the CPU"),
         ("One animal, one number", "Every point stitched onto a single ground plane"), ("Human review", "The player stops at each point to add or remove boxes"),
         ("Signed report", "Branded PDF signed with Ed25519")]
nodos = "".join(f"""<div style="flex:1;padding:0 8px;text-align:center">
   <div style="display:flex;align-items:center;height:20px;margin:0 -8px 18px">
     <div style="flex:1;height:1px;background:{'transparent' if i == 0 else 'rgba(255,255,255,.28)'}"></div>
     <div style="width:{16 if i == 0 else 10}px;height:{16 if i == 0 else 10}px;border-radius:50%;background:{'#e6dfd3' if i == 0 else 'rgba(255,255,255,.75)'};{'box-shadow:0 0 0 5px rgba(230,223,211,.25);' if i == 0 else ''}"></div>
     <div style="flex:1;height:1px;background:{'transparent' if i == len(pasos) - 1 else 'rgba(255,255,255,.28)'}"></div></div>
   <div class="sub" style="font-size:12px">Step {i + 1}</div>
   <h3 style="font-size:16px;line-height:1.3;margin:6px 0 8px">{t}</h3>
   <div class="sub" style="font-size:12.5px;line-height:1.45">{s}</div></div>""" for i, (t, s) in enumerate(pasos))
PIPE = f"""<div class="panel" id="x" style="padding:40px 22px 40px">
  <div style="display:flex">{nodos}</div></div>"""

cifras = [("−1.2 %", "Total count error", "466 test images · 6,240 animals"), ("91.9 %", "Precision", "Recall 90.8 % at confidence 0.30"),
          ("96 / 96", "No double counting", "Automated test on a simulated two-line flight")]
RES = f"""<div class="panel" id="x" style="padding:26px 26px 26px">
  <div style="display:flex;gap:16px">""" + "".join(f"""<div class="grad" style="flex:1;padding:34px 18px 32px;text-align:center">
    <div class="num" style="font-size:44px;letter-spacing:-.5px">{n}</div><h3 style="font-size:17px;margin:12px 0 8px">{t}</h3>
    <div class="sub" style="font-size:13px;line-height:1.45">{s}</div></div>""" for n, t, s in cifras) + """</div>
  <p class="sub" style="font-size:12.5px;text-align:center;margin-top:20px">Measured on the WAID dataset and on simulated flights built from it. Never tested in the field.</p></div>"""

ICO = {"cuadre": '<path d="M5 8h14M5 16h14M8 5l-3 3 3 3M16 13l3 3-3 3"/>',
       "candado": '<rect x="5.5" y="10.5" width="13" height="9" rx="2"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
       "firma": '<path d="M12 3.5l7 2.6v5.2c0 4.3-2.9 7.6-7 9.2-4.1-1.6-7-4.9-7-9.2V6.1z"/><path d="M9 12l2.2 2.2L15.2 10"/>'}
pilares = [("cuadre", "Inventory, not just counts", "Each count is compared with the previous one plus sales, purchases, births and deaths. Unexplained gaps are flagged."),
           ("candado", "Encrypted on the computer", "SQLCipher database (AES-256) with a key slot per user, a recovery code and encrypted backups."),
           ("firma", "Tamper-evident reports", "Ed25519 signature over the totals, the image hashes, the PDF hash and the audit-log hash.")]
PIL = f"""<div class="panel" id="x" style="padding:26px 26px 26px"><div class="soft" style="padding:34px 14px 36px;display:flex">""" + "".join(f"""<div style="flex:1;padding:0 18px;text-align:center">
    <div style="width:52px;height:52px;border-radius:50%;background:rgba(230,223,211,.1);display:inline-flex;align-items:center;justify-content:center">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{ICO[i]}</svg></div>
    <h3 style="font-size:17px;margin:16px 0 10px">{t}</h3><div class="sub" style="font-size:13.5px;line-height:1.5">{s}</div></div>""" for i, t, s in pilares) + "</div></div>"

BOTONES = {"btn_how": ("How it works", 0), "btn_results": ("Results", 0), "btn_showcase": ("Showcase", 0), "btn_security": ("Security", 0),
           "btn_run": ("Run it", 1), "btn_faq": ("FAQ", 0),
           "lnk_report": ("Sample signed report  →", 0), "lnk_ci": ("Windows build and tests  →", 0), "lnk_waid": ("WAID dataset  →", 0), "lnk_yolox": ("YOLOX  →", 0)}

with sync_playwright() as p:
    nav = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = nav.new_page(viewport={"width": 880, "height": 900}, device_scale_factor=2)
    for nombre, html in (("hero", HERO), ("pipeline", PIPE), ("results", RES), ("pillars", PIL)):
        pg.set_content(pagina(html)); pg.wait_for_timeout(250)
        pg.locator("#x").screenshot(path=os.path.join(SAL, nombre + ".png"), omit_background=True)
    for nombre, (texto, blanca) in BOTONES.items():
        pg.set_content(pagina(f'<span id="x" class="pill{" blanca" if blanca else ""}">{texto}</span>')); pg.wait_for_timeout(60)
        pg.locator("#x").screenshot(path=os.path.join(SAL, nombre + ".png"), omit_background=True)
    nav.close()
for f in sorted(os.listdir(SAL)): print(f, os.path.getsize(os.path.join(SAL, f)) // 1024, "KB")
