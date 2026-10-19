"""Documentos sintéticos (ficticios) para probar sin Gemini ni documentos reales."""
import io
import os
import sys

import cv2
import numpy as np
import pytest
from fpdf import FPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _qr_png(texto: str) -> bytes:
    codificador = cv2.QRCodeEncoder.create()
    qr = codificador.encode(texto)
    qr = cv2.resize(qr, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
    qr = cv2.copyMakeBorder(qr, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.imencode(".png", qr)[1].tobytes()


@pytest.fixture(scope="session")
def pdf_curp_digital() -> bytes:
    pdf = FPDF(format="A4")
    # Misma huella que las constancias reales (ver config_documentos.CURP["huella_origen"]).
    pdf.set_producer("iText 2.1.7 by 1T3XT")
    pdf.set_creator("JasperReports (report2)")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "ESTADOS UNIDOS MEXICANOS", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "CONSTANCIA DE LA CLAVE ÚNICA DE REGISTRO DE POBLACIÓN", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 8, "Clave:", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 8, "CARK800401MHGSDR09", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 8, "Nombre", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "KARLA ELIZABETH CASTILLO RODRIGUEZ", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Entidad de registro: HIDALGO", new_x="LMARGIN", new_y="NEXT")
    pdf.image(io.BytesIO(_qr_png("https://ejemplo.invalid/verificar?c=CARK800401MHGSDR09")), x=150, y=30, w=40)
    return bytes(pdf.output())


@pytest.fixture(scope="session")
def pdf_curp_escaneado(pdf_curp_digital) -> bytes:
    """Rasteriza el PDF digital y le agrega ruido/gradiente/JPEG: un 'escaneo' sin capa de texto."""
    import pypdfium2 as pdfium

    rgb = np.array(pdfium.PdfDocument(pdf_curp_digital)[0].render(scale=2).to_pil().convert("RGB"))
    f = rgb.astype(np.float32) * 0.94 + np.random.default_rng(1).normal(0, 4, rgb.shape)
    f += np.linspace(0, -10, f.shape[1])[None, :, None]
    img = np.clip(f, 0, 255).astype(np.uint8)
    jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
    pdf = FPDF(format="A4")
    pdf.add_page()
    pdf.image(io.BytesIO(jpg), x=0, y=0, w=210)
    return bytes(pdf.output())
