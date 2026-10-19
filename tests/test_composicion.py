import copy
import io

import pypdf

import captura
import composicion
from decision import evaluar
from test_decision import gem_ok

QR_CURP = "SOGA060701HHGTRLA7|SOGA060701HVZTRLA2, |SOTO|GARCIA|ALAN YAHIR|HOMBRE|01/07/2006|HIDALGO|30|"
QR_CERT = "http://siseems.sems.gob.mx/perfil/perfil_egresod.php?id_alumno=5789522"


def _pagina(texto="", qr=()):
    return {"texto": texto, "qr": list(qr)}


def test_el_codigo_identifica_la_pagina_por_qr_o_texto():
    assert composicion.tipo_por_codigo("", [QR_CURP])[0] == "curp"
    assert composicion.tipo_por_codigo("", [QR_CERT])[0] == "certificado_bachillerato"
    assert composicion.tipo_por_codigo("CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION", [])[0] == "curp"
    assert composicion.tipo_por_codigo("ACTA DE NACIMIENTO", ["IVAN ESQUIVEL A 1983J24"])[0] is None


def test_caso_real_acta_certificado_y_curp_en_un_solo_pdf():
    # Página 1: acta escaneada (sin texto; su QR no es de ningún tipo conocido) -> decide Gemini.
    # Página 2: certificado escaneado con QR de un dominio que no está en la lista -> decide Gemini.
    # Página 3: constancia digital -> la identifica el código por su QR.
    por_codigo = [_pagina(qr=["IVAN ESQUIVEL A 1983J24"]), _pagina(qr=["https://www.siged.sep.gob.mx/x"]),
                  _pagina(texto="CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION", qr=[QR_CURP])]
    modelo = [
        {"pagina": 1, "documento": "otro", "descripcion": "acta de nacimiento", "continuacion": False},
        {"pagina": 2, "documento": "certificado_bachillerato", "descripcion": "certificado", "continuacion": False},
        {"pagina": 3, "documento": "curp", "descripcion": "constancia de CURP", "continuacion": False},
    ]
    comp = composicion.combinar(por_codigo, modelo)
    assert [p["documento"] for p in comp] == ["otro", "certificado_bachillerato", "curp"]
    assert [p["fuente"] for p in comp] == ["gemini", "gemini", "codigo"]
    assert composicion.paginas_de(comp, "certificado_bachillerato") == [2]
    assert composicion.otros_documentos(comp, "certificado_bachillerato") == [
        "acta de nacimiento (pág. 1)", "constancia de CURP (pág. 3)"]


def test_el_reverso_de_un_certificado_no_cuenta_como_otro_documento():
    por_codigo = [_pagina(qr=[QR_CERT]), _pagina()]
    modelo = [
        {"pagina": 1, "documento": "certificado_bachillerato", "descripcion": "certificado", "continuacion": False},
        {"pagina": 2, "documento": "otro", "descripcion": "tabla de calificaciones", "continuacion": True},
    ]
    comp = composicion.combinar(por_codigo, modelo)
    assert composicion.paginas_de(comp, "certificado_bachillerato") == [1, 2]
    assert composicion.otros_documentos(comp, "certificado_bachillerato") == []


def test_el_codigo_manda_sobre_gemini():
    comp = composicion.combinar([_pagina(qr=[QR_CURP])],
                                [{"pagina": 1, "documento": "otro", "descripcion": "x", "continuacion": False}])
    assert comp[0]["documento"] == "curp" and comp[0]["fuente"] == "codigo"


def test_paginas_seguidas_del_mismo_documento_se_agrupan():
    comp = [{"pagina": n, "documento": d, "descripcion": desc} for n, d, desc in
            [(1, "otro", "acta de nacimiento"), (2, "otro", "acta de nacimiento"), (3, "curp", "constancia de CURP")]]
    assert composicion.otros_documentos(comp, "curp") == ["acta de nacimiento (págs. 1-2)"]


def test_extraer_paginas_conserva_paginas_y_metadatos(pdf_curp_digital):
    escritor = pypdf.PdfWriter()
    for _ in range(3):
        escritor.add_page(pypdf.PdfReader(io.BytesIO(pdf_curp_digital)).pages[0])
    escritor.add_metadata({"/Producer": "iText 2.1.7 by 1T3XT"})
    buf = io.BytesIO(); escritor.write(buf)
    extraido = pypdf.PdfReader(io.BytesIO(composicion.extraer_paginas(buf.getvalue(), [2, 3])))
    assert len(extraido.pages) == 2 and extraido.metadata["/Producer"].startswith("iText")


def test_otros_documentos_en_el_archivo_rechaza(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    comp = [{"pagina": 1, "documento": "otro", "descripcion": "acta de nacimiento", "fuente": "gemini", "evidencia": None},
            {"pagina": 2, "documento": "curp", "descripcion": "constancia de CURP", "fuente": "codigo", "evidencia": None}]
    r = evaluar("curp", copy.deepcopy(info), gem_ok(), composicion=comp)
    assert r["resultado"] == "rechazado" and r["paginas_analizadas"] == [2]
    assert any("acta de nacimiento (pág. 1)" in m and "solo la constancia de CURP" in m for m in r["motivos"])


def test_documento_de_una_sola_pieza_no_cambia(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    r = evaluar("curp", info, gem_ok(), composicion=None)
    assert r["composicion"] is None and r["paginas_analizadas"] is None
