"""Verifica un reporte firmado. No necesita la aplicacion ni la base de datos.

  python verificar.py reporte_conteo.pdf
  python verificar.py reporte_conteo.pdf --llave llave_publica.pem --fotos carpeta_del_vuelo

Junto al PDF debe estar su archivo de firma (reporte_conteo.pdf.firma.json).
Comprueba:
  1. que el PDF es el mismo que se firmo (huella SHA-256),
  2. que los datos del conteo no se cambiaron (firma Ed25519),
  3. con --llave, que lo firmo quien dice ser (la llave publica que te dio el emisor),
  4. con --fotos, que las fotos de esa carpeta son las mismas que se contaron.

Lo que una firma NO prueba: que las fotos sean de esa finca o de esa fecha, ni
que el conteo este bien hecho. Prueba que nadie cambio el reporte despues de emitido.

Necesita: cryptography.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import seguridad


def verificar(pdf, llave_confiable=None, carpeta_fotos=None):
    """Devuelve (ok, lineas). ok es False si alguna comprobacion falla."""
    lineas, ok = [], True

    def paso(bien, texto):
        nonlocal ok
        ok = ok and bien
        lineas.append(("  ok     " if bien else "  FAIL   ") + texto)

    ruta_firma = pdf + ".firma.json"
    if not os.path.exists(ruta_firma):
        return False, [f"  FAIL   The signature file is missing: {os.path.basename(ruta_firma)}"]
    with open(ruta_firma, encoding="utf8") as fh:
        sobre = json.load(fh)
    man, pub = sobre["manifiesto"], sobre["llave_publica"]

    paso(seguridad.sha256_archivo(pdf) == sobre["pdf_sha256"], "The PDF is the one that was signed")
    firmado = seguridad.canonico({"manifiesto": man, "pdf_sha256": sobre["pdf_sha256"]})
    paso(seguridad.firma_valida(pub, firmado, sobre["firma"]), "The count data was not changed")

    huella = seguridad.huella_llave(pub)
    if llave_confiable:
        with open(llave_confiable, encoding="ascii") as fh:
            esperada = seguridad.huella_llave(fh.read())
        paso(huella == esperada, f"Signed with the issuer's key ({esperada})")
    else:
        lineas.append(f"  note   The key's owner was not checked. Fingerprint of the signing key: {huella}")
        lineas.append("         Compare it with the one the issuer gave you, or use --llave.")

    if carpeta_fotos:
        for f in man["fotos"]:
            ruta = os.path.join(carpeta_fotos, f["nombre"])
            if not os.path.exists(ruta):
                paso(False, f"Image {f['nombre']}: not in the folder")
            else:
                paso(seguridad.sha256_archivo(ruta) == f["sha256"], f"Image {f['nombre']}: same as the one counted")

    lineas.append("")
    lineas.append(f"  Ranch: {man['finca']}   Owner: {man['propietario'] or '—'}")
    lineas.append(f"  Flight date: {man['fecha_vuelo']}   Issued: {man['emitido']}   By: {man['usuario']}")
    lineas.append(f"  Signed total: {man['total']} cattle  (model {man['ia']}, added {man['manual']}, "
                  f"removed {man['quitadas']})   Images: {len(man['fotos'])}, "
                  f"reviewed {sum(1 for f in man['fotos'] if f['revisada'])}")
    return ok, lineas


def main():
    ap = argparse.ArgumentParser(description="Verifies a signed count report")
    ap.add_argument("pdf")
    ap.add_argument("--llave", help="issuer's public key (llave_publica.pem)")
    ap.add_argument("--fotos", help="folder with the flight's original images")
    a = ap.parse_args()
    ok, lineas = verificar(a.pdf, a.llave, a.fotos)
    print("\n".join(lineas))
    print("\nVALID REPORT" if ok else "\nINVALID REPORT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
