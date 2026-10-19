"""Reglas deterministas de la CURP (no dependen de ningún modelo).

Estructura (18 caracteres): AAAA YYMMDD S EE CCC H D
  AAAA   iniciales del nombre (letra, vocal, letra, letra)
  YYMMDD fecha de nacimiento
  S      sexo (H, M, X)
  EE     entidad federativa de nacimiento (o NE = nacido en el extranjero)
  CCC    primeras consonantes internas
  H      homoclave: dígito (nacidos hasta 1999) o letra (desde 2000)
  D      dígito verificador
"""
import re
import unicodedata
from datetime import date

ENTIDADES = {
    "AS": "Aguascalientes", "BC": "Baja California", "BS": "Baja California Sur",
    "CC": "Campeche", "CL": "Coahuila", "CM": "Colima", "CS": "Chiapas", "CH": "Chihuahua",
    "DF": "Ciudad de México", "DG": "Durango", "GT": "Guanajuato", "GR": "Guerrero",
    "HG": "Hidalgo", "JC": "Jalisco", "MC": "México", "MN": "Michoacán", "MS": "Morelos",
    "NT": "Nayarit", "NL": "Nuevo León", "OC": "Oaxaca", "PL": "Puebla", "QT": "Querétaro",
    "QR": "Quintana Roo", "SP": "San Luis Potosí", "SL": "Sinaloa", "SR": "Sonora",
    "TC": "Tabasco", "TS": "Tamaulipas", "TL": "Tlaxcala", "VZ": "Veracruz", "YN": "Yucatán",
    "ZS": "Zacatecas", "NE": "Nacido en el extranjero",
}

# Clave numérica de entidad (la que trae el QR de la constancia) -> abreviatura de la CURP.
CODIGO_ENTIDAD = {
    "01": "AS", "02": "BC", "03": "BS", "04": "CC", "05": "CL", "06": "CM", "07": "CS", "08": "CH",
    "09": "DF", "10": "DG", "11": "GT", "12": "GR", "13": "HG", "14": "JC", "15": "MC", "16": "MN",
    "17": "MS", "18": "NT", "19": "NL", "20": "OC", "21": "PL", "22": "QT", "23": "QR", "24": "SP",
    "25": "SL", "26": "SR", "27": "TC", "28": "TS", "29": "TL", "30": "VZ", "31": "YN", "32": "ZS",
}
# Nombres alternativos con que figuran las entidades en los documentos.
_ALIAS_ENTIDAD = {
    "DISTRITO FEDERAL": "DF", "CDMX": "DF", "ESTADO DE MEXICO": "MC",
    "COAHUILA DE ZARAGOZA": "CL", "MICHOACAN DE OCAMPO": "MN",
    "VERACRUZ DE IGNACIO DE LA LLAVE": "VZ", "VERACRUZ LLAVE": "VZ",
}

PATRON = re.compile(
    r"^[A-Z][AEIOUX][A-Z]{2}\d{2}\d{2}\d{2}[HMX]"
    r"(?:" + "|".join(ENTIDADES) + r")"
    r"[B-DF-HJ-NP-TV-Z]{3}[0-9A-Z]\d$"
)
DICCIONARIO = "0123456789ABCDEFGHIJKLMNÑOPQRSTUVWXYZ"


def _sin_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return re.sub(r"\s+", " ", "".join(c for c in texto if not unicodedata.combining(c))).upper().strip()


def entidad_a_abreviatura(nombre: str | None) -> str | None:
    """'Hidalgo', 'DISTRITO FEDERAL', 'Veracruz de Ignacio de la Llave' -> 'HG', 'DF', 'VZ'. None si no se reconoce."""
    clave = _sin_acentos(nombre)
    if clave in _ALIAS_ENTIDAD:
        return _ALIAS_ENTIDAD[clave]
    for abrev, oficial in ENTIDADES.items():
        if abrev != "NE" and _sin_acentos(oficial) == clave:
            return abrev
    return None


def palabras_nombre(texto: str | None) -> frozenset[str]:
    """Palabras de un nombre sin acentos ni puntuación: para comparar sin importar el orden."""
    return frozenset(re.findall(r"[A-ZÑ]+", _sin_acentos(texto).replace("Ñ", "N")))


def datos_qr_curp(texto: str) -> dict | None:
    """Desarma el QR de la constancia: CLAVE|ASOCIADA|APELLIDO1|APELLIDO2|NOMBRE|SEXO|DD/MM/AAAA|ENTIDAD|COD|"""
    partes = [p.strip() for p in texto.split("|")]
    if len(partes) < 8 or not PATRON.match(limpiar(partes[0])):
        return None
    return {
        "clave": limpiar(partes[0]),
        "clave_asociada": partes[1].strip(" ,") or None,
        "apellido_paterno": partes[2] or None,
        "apellido_materno": partes[3] or None,
        "nombre": partes[4] or None,
        "sexo": partes[5] or None,
        "fecha_nacimiento": partes[6] or None,
        "entidad_nacimiento": partes[7] or None,
        "codigo_entidad_registro": partes[8] if len(partes) > 8 and partes[8] else None,
    }


def datos_texto_constancia(lineas: list[str]) -> dict | None:
    """Clave, nombre y entidad de registro desde la capa de texto de la constancia (PDF digital).

    En los modelos vistos (actual y SEGOB) el texto trae, en este orden:
        NOMBRE / número del código de barras (15 dígitos) / CLAVE / NOMBRE
    y la entidad pegada a la etiqueta ('VERACRUZEntidad de registro:') o en la línea anterior.
    Se toma la CURP que sigue al número de barras (no la de "CURP's asociadas"). None si no se reconoce.
    """
    datos = {}
    for i in range(1, len(lineas)):
        if re.fullmatch(r"\d{12,20}", lineas[i - 1]) and PATRON.match(limpiar(lineas[i])):
            datos["clave"] = limpiar(lineas[i])
            if i + 1 < len(lineas) and not PATRON.match(limpiar(lineas[i + 1])):
                datos["nombre"] = lineas[i + 1]
            break
    if "clave" not in datos:
        return None
    for i, linea in enumerate(lineas):
        etiqueta = re.search(r"entidad\s+de\s+registro", linea, re.I)
        if not etiqueta:
            continue
        previa = linea[:etiqueta.start()].strip() or (lineas[i - 1].strip() if i > 0 else "")
        if previa and not re.search(r"\d", previa):
            datos["entidad_registro"] = previa
        break
    return datos


def limpiar(curp: str | None) -> str:
    return (curp or "").strip().upper().replace(" ", "")


def digito_verificador(primeros_17: str) -> int:
    suma = sum(DICCIONARIO.index(c) * (18 - i) for i, c in enumerate(primeros_17))
    return (10 - suma % 10) % 10


def fecha_nacimiento(curp: str) -> date | None:
    yy, mm, dd = int(curp[4:6]), int(curp[6:8]), int(curp[8:10])
    siglo = 1900 if curp[16].isdigit() else 2000
    try:
        return date(siglo + yy, mm, dd)
    except ValueError:
        return None


_LETRA_A_DIGITO = str.maketrans("OI", "01")
_POSICIONES_DIGITO = [*range(4, 10), 17]  # fecha AAMMDD y dígito verificador: siempre dígitos


def _corregir_lectura(curp: str) -> str:
    """Confusiones típicas de lectura (O por 0, I por 1) en las posiciones que solo admiten dígitos."""
    letras = list(curp)
    for i in _POSICIONES_DIGITO:
        letras[i] = letras[i].translate(_LETRA_A_DIGITO)
    return "".join(letras)


def validar(curp: str | None) -> dict:
    """Devuelve {valida, errores, entidad, fecha_nacimiento, sexo}.

    Si la CURP leída no es válida pero lo es cambiando O/I por 0/1 donde solo caben dígitos,
    se da por válida y se informa en `corregida_desde` (el dígito verificador respalda el cambio).
    """
    resultado = _validar(curp)
    leida = limpiar(curp)
    if not resultado["valida"] and len(leida) == 18:
        candidata = _corregir_lectura(leida)
        if candidata != leida:
            corregida = _validar(candidata)
            if corregida["valida"]:
                return corregida | {"corregida_desde": leida, "curp_corregida": candidata}
    return resultado


def _validar(curp: str | None) -> dict:
    curp = limpiar(curp)
    errores = []
    if len(curp) != 18:
        return {"valida": False, "errores": [f"Longitud {len(curp)}, se esperaban 18 caracteres"]}
    if not PATRON.match(curp):
        errores.append("No cumple la estructura de una CURP")
    else:
        nacimiento = fecha_nacimiento(curp)
        if nacimiento is None:
            errores.append("La fecha de nacimiento no existe en el calendario")
        elif nacimiento > date.today():
            errores.append("La fecha de nacimiento es futura")
        if int(curp[17]) != digito_verificador(curp[:17]):
            errores.append("El dígito verificador no coincide (posible error de lectura o CURP inventada)")
    return {
        "valida": not errores,
        "errores": errores,
        "entidad": ENTIDADES.get(curp[11:13]),
        "fecha_nacimiento": (lambda f: f.isoformat() if f else None)(
            fecha_nacimiento(curp) if PATRON.match(curp) else None
        ),
        "sexo": curp[10],
    }
