import copy

import captura
from config_documentos import DOCUMENTOS
from decision import evaluar


def gem_ok(tipo="curp", clave="CARK800401MHGSDR09"):
    cfg = DOCUMENTOS[tipo]
    r = {
        "tipo_detectado": tipo,
        "captura": "digital_original",
        "variante": "electronico" if tipo == "certificado_bachillerato" else None,
        "checks": {c: {"presente": True, "evidencia": "visible"} for c in cfg["checks"]},
        "campos": {c: None for c in cfg["campos"]} | {cfg["campo_clave"]: clave},
    }
    if tipo == "certificado_bachillerato":  # por defecto, un certificado electrónico: sin firma ni foto
        for c in ("firma_autografa", "foto_del_alumno"):
            r["checks"][c]["presente"] = False
    return r


def test_curp_digital_correcta_se_acepta(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    r = evaluar("curp", info, gem_ok())
    # Los elementos que solo se ven (logos, bandera, barras) no existen en el PDF sintético
    # y se resuelven por Gemini (mockeado en true); los de texto se verifican en el PDF.
    assert r["checks"]["leyenda_estados_unidos_mexicanos"]["fuente"] == "texto_pdf"
    assert r["checks"]["codigo_qr"]["fuente"] == "codigo"
    assert r["resultado"] == "aceptado", r["motivos"]


def test_pdf_escaneado_se_rechaza(pdf_curp_escaneado):
    info = captura.analizar(pdf_curp_escaneado, "application/pdf")
    r = evaluar("curp", info, gem_ok())
    assert r["resultado"] == "rechazado"
    assert any("escaneo" in m.lower() for m in r["motivos"])


def test_imagen_se_rechaza_o_revisa_segun_config(pdf_curp_digital):
    import cv2, numpy as np
    img = cv2.imencode(".png", np.full((200, 200, 3), 255, np.uint8))[1].tobytes()
    info = captura.analizar(img, "image/png")
    assert evaluar("curp", info, gem_ok())["resultado"] == "rechazado"
    assert evaluar("curp", info, gem_ok(), aceptar_imagenes=True)["resultado"] != "rechazado"


def test_falta_elemento_critico_rechaza(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    info = copy.deepcopy(info)
    info["texto"] = info["texto"].replace("CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION", "")
    gem = gem_ok()
    gem["checks"]["leyenda_constancia_curp"]["presente"] = False
    r = evaluar("curp", info, gem)
    assert r["resultado"] == "rechazado"
    assert any("obligatorio" in m for m in r["motivos"])


def test_leyenda_fuera_de_la_capa_de_texto_la_resuelve_gemini(pdf_curp_digital):
    # Caso real: el encabezado de la CURP es una imagen, no está en el texto del PDF.
    info = copy.deepcopy(captura.analizar(pdf_curp_digital, "application/pdf"))
    info["texto"] = info["texto"].replace("CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION", "")
    r = evaluar("curp", info, gem_ok())
    assert r["checks"]["leyenda_constancia_curp"]["fuente"] == "gemini"
    assert r["resultado"] == "aceptado", r["motivos"]


def test_curp_con_digito_incorrecto_pasa_a_revisar(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    r = evaluar("curp", info, gem_ok(clave="CARK800401MHGSDR08"))
    assert r["resultado"] == "revisar"


def test_tipo_equivocado_rechaza(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    gem = gem_ok()
    gem["tipo_detectado"] = "certificado_bachillerato"
    assert evaluar("curp", info, gem)["resultado"] == "rechazado"


def _info_certificado(pdf, qr):
    info = copy.deepcopy(captura.analizar(pdf, "application/pdf"))
    info["texto"] += " CERTIFICADO DE BACHILLERATO"
    info["qr"] = qr
    return info


def test_certificado_provisorio_nunca_se_acepta(pdf_curp_digital, monkeypatch):
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "provisorio", True)
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "qr_dominios", {"ejemplo.invalid"})
    info = _info_certificado(pdf_curp_digital, ["https://ejemplo.invalid/verificar"])
    r = evaluar("certificado_bachillerato", info, gem_ok("certificado_bachillerato"))
    assert r["resultado"] == "revisar"


def test_certificado_con_qr_oficial_se_acepta(pdf_curp_digital, monkeypatch):
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "qr_dominios", {"ejemplo.invalid"})
    info = _info_certificado(pdf_curp_digital, ["https://ejemplo.invalid/verificar?curp=CARK800401MHGSDR09"])
    r = evaluar("certificado_bachillerato", info, gem_ok("certificado_bachillerato"))
    assert r["resultado"] == "aceptado", r["motivos"]


def test_certificado_con_qr_de_dominio_ajeno_se_revisa(pdf_curp_digital):
    info = _info_certificado(pdf_curp_digital, ["https://sitio-falso.example/verificar"])
    r = evaluar("certificado_bachillerato", info, gem_ok("certificado_bachillerato"))
    assert r["resultado"] == "revisar"
    assert any("dominio no reconocido" in m for m in r["motivos"])


def test_certificado_con_curp_del_qr_distinta_se_revisa(pdf_curp_digital, monkeypatch):
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "qr_dominios", {"ejemplo.invalid"})
    info = _info_certificado(pdf_curp_digital, ["https://ejemplo.invalid/v?curp=AUGN991207MDFGRY08"])
    r = evaluar("certificado_bachillerato", info, gem_ok("certificado_bachillerato"))
    assert r["resultado"] == "revisar"
    assert any("no coincide" in m for m in r["motivos"])


def test_certificado_sin_qr_se_rechaza(pdf_curp_escaneado):
    info = captura.analizar(pdf_curp_escaneado, "application/pdf")
    info = copy.deepcopy(info) | {"qr": [], "qr_detectados": 0}
    gem = gem_ok("certificado_bachillerato")
    gem["checks"]["codigo_qr"]["presente"] = False
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["resultado"] == "rechazado"
    assert any("Código QR" in m for m in r["motivos"])


def test_varios_importantes_faltantes_rechaza(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    gem = gem_ok()
    for c in ("etiqueta_nombre", "bandera_mexico", "codigo_barras"):
        gem["checks"][c]["presente"] = False
    assert evaluar("curp", info, gem)["resultado"] == "rechazado"


def test_un_importante_faltante_revisa(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    gem = gem_ok()
    gem["checks"]["bandera_mexico"]["presente"] = False
    assert evaluar("curp", info, gem)["resultado"] == "revisar"


def test_curp_sin_logos_institucionales_se_acepta(pdf_curp_digital):
    # Modelo anterior de la constancia (logo SEGOB): los logos del pie no existen y es válido.
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    gem = gem_ok()
    gem["checks"]["logos_institucionales"]["presente"] = False
    r = evaluar("curp", info, gem)
    assert r["resultado"] == "aceptado", r["motivos"]


def test_detalle_del_qr_desarma_la_url(pdf_curp_digital, monkeypatch):
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "qr_dominios", {"ejemplo.invalid"})
    info = _info_certificado(pdf_curp_digital, ["https://ejemplo.invalid/perfil.php?id_alumno=123&curp=CARK800401MHGSDR09"])
    d = evaluar("certificado_bachillerato", info, gem_ok("certificado_bachillerato"))["qr"]["detalle"][0]
    assert d["dominio"] == "ejemplo.invalid" and d["dominio_oficial"] is True
    assert d["parametros"] == {"id_alumno": "123", "curp": "CARK800401MHGSDR09"}


def test_curp_con_marca_de_terceros_se_rechaza(pdf_curp_digital):
    # Caso real: constancia con marca de agua de CamScanner.
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    gem = gem_ok()
    gem["checks"]["sin_marcas_de_terceros"] = {"presente": False, "evidencia": "logo CamScanner"}
    r = evaluar("curp", info, gem)
    assert r["resultado"] == "rechazado"
    assert any(m.startswith("Tiene una marca de agua") and "CamScanner" in m for m in r["motivos"])


def test_curp_con_imagenes_de_mas_se_revisa(pdf_curp_digital):
    info = copy.deepcopy(captura.analizar(pdf_curp_digital, "application/pdf"))
    info["imagenes_embebidas"] = DOCUMENTOS["curp"]["max_imagenes_embebidas"] + 1
    r = evaluar("curp", info, gem_ok())
    assert r["resultado"] == "revisar"
    assert any("marca de agua" in m for m in r["motivos"])


def _cert(pdf, monkeypatch, **checks):
    monkeypatch.setitem(DOCUMENTOS["certificado_bachillerato"], "qr_dominios", {"ejemplo.invalid"})
    info = _info_certificado(pdf, ["https://ejemplo.invalid/verificar"])
    gem = gem_ok("certificado_bachillerato")
    for c, v in checks.items():
        gem["checks"][c]["presente"] = v
    return info, gem


def test_semielectronico_con_firma_autografa_se_acepta(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch, firma_autografa=True, sello_o_firma_electronica=False)
    gem["variante"] = "semielectronico"
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["variante"] == "semielectronico" and r["resultado"] == "aceptado", r["motivos"]


def test_semielectronico_sin_firma_se_revisa(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch, firma_autografa=False, sello_o_firma_electronica=False)
    gem["variante"] = "semielectronico"
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["resultado"] == "revisar"
    assert any("firma manuscrita" in m.lower() for m in r["motivos"])


def test_electronico_sin_sello_se_revisa(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch, sello_o_firma_electronica=False)
    # sin ninguna de las dos señales no hay base para corregir la etiqueta: se mantiene la del modelo
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["variante"] == "electronico" and r["resultado"] == "revisar"


def test_variante_se_corrige_por_lo_que_se_ve(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch, firma_autografa=True, sello_o_firma_electronica=False)
    gem["variante"] = "electronico"  # el modelo la etiquetó mal
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["variante"] == "semielectronico" and r["variante_segun_modelo"] == "electronico"


def test_enlace_impreso_de_otro_dominio_se_revisa(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch)
    gem["campos"]["enlace_verificacion_impreso"] = "http://otro-sitio.example/perfil?id=1"
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["resultado"] == "revisar" and any("no coincide con el dominio del QR" in m for m in r["motivos"])


def test_enlace_impreso_sin_esquema_se_normaliza_y_compara(pdf_curp_digital, monkeypatch):
    info, gem = _cert(pdf_curp_digital, monkeypatch)
    gem["campos"]["enlace_verificacion_impreso"] = "www.otro-sitio.example/certificados"
    r = evaluar("certificado_bachillerato", info, gem)
    assert r["qr"]["enlace_impreso"] == "http://www.otro-sitio.example/certificados"
    assert any("no coincide con el dominio del QR" in m for m in r["motivos"])
    gem["campos"]["enlace_verificacion_impreso"] = "ejemplo.invalid/verificar"
    assert not any("no coincide" in m for m in evaluar("certificado_bachillerato", info, gem)["motivos"])


QR_CURP = "SOGA060701HHGTRLA7|SOGA060701HVZTRLA2, |SOTO|GARCIA|ALAN YAHIR|HOMBRE|01/07/2006|HIDALGO|30|"


def _curp_con_qr(pdf, qr, **campos):
    info = copy.deepcopy(captura.analizar(pdf, "application/pdf")) | {"qr": [qr]}
    gem = gem_ok(clave="SOGA060701HHGTRLA7")
    gem["campos"] |= {"nombre": "ALAN YAHIR SOTO GARCIA", "entidad_registro": "VERACRUZ"} | campos
    return evaluar("curp", info, gem)


def test_qr_curp_coherente_con_el_documento_se_acepta(pdf_curp_digital):
    r = _curp_con_qr(pdf_curp_digital, QR_CURP)
    assert not any("QR" in m and "no coincide" in m for m in r["motivos"]), r["motivos"]
    assert r["qr"]["detalle"][0]["datos"]["nombre"] == "ALAN YAHIR"


def test_qr_curp_con_nombre_distinto_se_revisa(pdf_curp_digital):
    r = _curp_con_qr(pdf_curp_digital, QR_CURP, nombre="ALAN YAHIR SOTO LOPEZ")
    assert r["resultado"] == "revisar" and any("nombre del QR" in m for m in r["motivos"])


def test_qr_curp_con_fecha_o_sexo_o_entidad_distintos_se_revisa(pdf_curp_digital):
    for cambio, texto in (("01/07/2006", "02/07/2006"), ("HOMBRE", "MUJER"), ("|HIDALGO|", "|JALISCO|")):
        r = _curp_con_qr(pdf_curp_digital, QR_CURP.replace(cambio, texto))
        assert r["resultado"] == "revisar" and any("QR" in m and "no coincide" in m for m in r["motivos"]), cambio


def test_qr_curp_con_entidad_de_registro_distinta_se_revisa(pdf_curp_digital):
    r = _curp_con_qr(pdf_curp_digital, QR_CURP, entidad_registro="CHIAPAS")
    assert any("entidad de registro" in m for m in r["motivos"])


def test_nombres_de_entidad_con_variantes_se_reconocen():
    import reglas_curp as rc
    assert rc.entidad_a_abreviatura("DISTRITO FEDERAL") == "DF"
    assert rc.entidad_a_abreviatura("MICHOACAN DE OCAMPO") == "MN"
    assert rc.entidad_a_abreviatura("Yucatán") == "YN"
    assert rc.entidad_a_abreviatura("Atlantida") is None


def test_pdf_con_texto_y_poco_blanco_puro_se_revisa(pdf_curp_digital):
    info = copy.deepcopy(captura.analizar(pdf_curp_digital, "application/pdf")) | {"blanco_puro": 0.65}
    r = evaluar("curp", info, gem_ok())
    assert r["resultado"] == "revisar" and any("blanco exacto" in m for m in r["motivos"])


def test_pdf_de_otro_generador_se_revisa(pdf_curp_digital):
    info = copy.deepcopy(captura.analizar(pdf_curp_digital, "application/pdf")) | {"productor": "iLovePDF", "creador": None}
    r = evaluar("curp", info, gem_ok())
    assert r["resultado"] == "revisar" and any("iLovePDF" in m for m in r["motivos"])


def test_pdf_modificado_despues_de_generarse_se_revisa(pdf_curp_digital):
    info = copy.deepcopy(captura.analizar(pdf_curp_digital, "application/pdf"))
    info |= {"fecha_creacion": "D:20250203104317-06'00'", "fecha_modificacion": "D:20250210090000-06'00'"}
    r = evaluar("curp", info, gem_ok())
    assert r["resultado"] == "revisar" and any("modificado después" in m for m in r["motivos"])


def test_huella_oficial_no_genera_avisos(pdf_curp_digital):
    info = captura.analizar(pdf_curp_digital, "application/pdf")
    assert info["productor"].startswith("iText") and info["blanco_puro"] >= 0.70
    assert not any("generado por el sistema" in m or "blanco exacto" in m for m in evaluar("curp", info, gem_ok())["motivos"])


LINEAS_CONSTANCIA = [
    "PRESENTE", "ALAN YAHIR SOTO GARCIA", "130087200605092", "SOGA060701HHGTRLA7", "ALAN YAHIR SOTO GARCIA",
    "Clave:", "Nombre", "SOGA060701HVZTRLA2", "CURP's asociadas por corrección", "VERACRUZEntidad de registro:",
]


def test_campos_de_la_constancia_se_extraen_del_texto():
    import reglas_curp as rc
    assert rc.datos_texto_constancia(LINEAS_CONSTANCIA) == {
        "clave": "SOGA060701HHGTRLA7", "nombre": "ALAN YAHIR SOTO GARCIA", "entidad_registro": "VERACRUZ"}
    # modelo SEGOB: la entidad va en la línea anterior a la etiqueta
    segob = ["MARIBEL LOPEZ NAVARRO", "111007198306227", "LONM760202MGTPVR03", "MARIBEL LOPEZ NAVARRO",
             "GUANAJUATO", "Entidad de registro"]
    assert rc.datos_texto_constancia(segob)["entidad_registro"] == "GUANAJUATO"
    assert rc.datos_texto_constancia(["sin", "formato"]) is None


def _curp_texto(pdf, **vistos):
    info = copy.deepcopy(captura.analizar(pdf, "application/pdf")) | {"lineas_texto": LINEAS_CONSTANCIA, "qr": []}
    gem = gem_ok(clave="SOGA060701HHGTRLA7")
    gem["campos"] |= {"nombre": "ALAN YAHIR SOTO GARCIA", "entidad_registro": "VERACRUZ"} | vistos
    return evaluar("curp", info, gem)


def test_el_texto_del_pdf_manda_sobre_la_lectura_de_gemini(pdf_curp_digital):
    r = _curp_texto(pdf_curp_digital, clave="EARH050dYA8")  # lectura defectuosa real
    assert r["campos"]["clave"] == "SOGA060701HHGTRLA7" and r["campos_fuente"]["clave"] == "texto_pdf"
    assert r["campo_clave"]["validacion"]["valida"]
    assert any("no coincide con el texto del PDF" in m for m in r["motivos"])


def test_lectura_coincidente_no_genera_avisos(pdf_curp_digital):
    r = _curp_texto(pdf_curp_digital, entidad_registro="Veracruz de Ignacio de la Llave", nombre="Alan Yahir Soto García")
    assert not any("no coincide con el texto del PDF" in m for m in r["motivos"]), r["motivos"]


def test_error_de_una_letra_en_la_lectura_se_tolera_pero_otro_nombre_no(pdf_curp_digital):
    from decision import _mismo_valor
    assert _mismo_valor("entidad_registro", "MICHOACAN DE OCAMPO", "MICHOACAN DE OCAMPI")  # caso real
    assert _mismo_valor("nombre", "JUAN DAVID PALOMINO GARCIA", "JUAN DAVID PALOMIN0 GARCIA")
    assert not _mismo_valor("nombre", "ALAN YAHIR SOTO GARCIA", "ALAN YAHIR SOTO LOPEZ")
    assert not _mismo_valor("nombre", "ALAN YAHIR SOTO GARCIA", "MARIA FERNANDA RUIZ PEREZ")
    assert not _mismo_valor("clave", "SOGA060701HHGTRLA7", "SOGA060701HHGTRLA8")  # la clave es estricta


def test_cambio_de_una_letra_en_un_nombre_corto_se_detecta():
    from decision import _mismo_valor
    assert not _mismo_valor("nombre", "MARIA LOPEZ", "MARIO LOPEZ")
