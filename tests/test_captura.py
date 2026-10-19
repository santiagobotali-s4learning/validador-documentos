import captura


def test_pdf_digital(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    assert info["digital_pdf"] is True
    assert "ESTADOS UNIDOS MEXICANOS" in info["texto"]
    assert info["blanco_puro"] > 0.5


def test_qr_del_pdf_digital_se_lee(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    assert info["qr"] and info["qr"][0].startswith("https://ejemplo.invalid")


def test_pdf_escaneado_no_es_digital(pdf_curp_escaneado):
    info = captura.analizar(pdf_curp_escaneado, "application/pdf")
    assert info["digital_pdf"] is False
    assert info["caracteres_texto"] < captura.MIN_CHARS_TEXTO


def test_normalizar_quita_acentos():
    assert captura.normalizar("Única  de   Población") == "UNICA DE POBLACION"
    assert captura.normalizar("Clave :") == "CLAVE:"


def test_pdf_con_texto_se_envia_a_gemini_como_imagen_y_el_escaneo_como_pdf(pdf_curp_digital, pdf_curp_escaneado):
    digital = captura.envio_a_gemini(pdf_curp_digital, "application/pdf")
    assert digital and all(mime == "image/png" for _, mime in digital)
    escaneo = captura.envio_a_gemini(pdf_curp_escaneado, "application/pdf")
    assert escaneo == [(pdf_curp_escaneado, "application/pdf")]
    # el interruptor vuelve a enviar siempre el PDF
    assert captura.envio_a_gemini(pdf_curp_digital, "application/pdf", pdf_como_imagen=False)[0][1] == "application/pdf"
