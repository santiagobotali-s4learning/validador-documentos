import reglas_curp as r


def test_curp_del_ejemplo_es_valida():
    v = r.validar("CARK800401MHGSDR09")
    assert v["valida"] and v["entidad"] == "Hidalgo" and v["fecha_nacimiento"] == "1980-04-01"


def test_digito_verificador_incorrecto():
    v = r.validar("CARK800401MHGSDR08")
    assert not v["valida"] and "verificador" in v["errores"][0]


def test_entidad_inexistente():
    assert not r.validar("CARK800401MXXSDR09")["valida"]


def test_fecha_inexistente():
    assert not r.validar("CARK800230MHGSDR09")["valida"]  # 30 de febrero


def test_longitud_y_espacios():
    assert not r.validar("CARK8004")["valida"]
    assert r.validar(" cark800401mhgsdr09 ")["valida"]


def test_none():
    assert not r.validar(None)["valida"]


def test_letra_o_por_cero_en_posicion_de_digito_se_corrige():
    # Caso real: el modelo leyó la letra O donde el documento tiene el dígito 0.
    v = r.validar("IUDR040218MTCDGGAO")
    assert v["valida"] and v["corregida_desde"] == "IUDR040218MTCDGGAO"
    assert v["curp_corregida"] == "IUDR040218MTCDGGA0"


def test_no_se_corrige_si_igual_es_invalida():
    # Mismo cambio O->0, pero el dígito verificador no cierra: no se acepta.
    assert not r.validar("IUDR040218MTCDGGB0")["valida"]
    assert "corregida_desde" not in r.validar("IUDR040218MTCDGGB0")
