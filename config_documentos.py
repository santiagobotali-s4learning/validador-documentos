"""Qué hace que un documento tenga el formato correcto, por tipo.

Cada check tiene un nivel:
  critico    -> si falta, el documento se RECHAZA.
  importante -> si falta, el documento pasa a REVISAR (puede ser una variante o mala captura).
  opcional   -> solo se informa (p. ej. la 2.ª hoja puede no haberse subido).

`patrones` (opcional): textos que, en un PDF digital con capa de texto, se buscan por código
(sin Gemini) comparando en mayúsculas y sin acentos. Es la evidencia más fuerte.
"""

# Cuántos checks "importante" pueden faltar antes de pasar de REVISAR a RECHAZADO. Provisorio:
# ajustar con documentos reales (buenos y malos).
MAX_IMPORTANTES_FALTANTES = 1

CURP = {
    "nombre": "Constancia de CURP (digital)",
    "nombre_corto": "constancia de CURP",
    "articulo": "la",
    "requiere_pdf_digital": True,
    "campos": {
        "clave": "Clave CURP de 18 caracteres, tal como figura en la constancia",
        "nombre": "Nombre completo de la persona, tal como figura en la constancia",
        "entidad_registro": "Entidad de registro",
    },
    "campo_clave": "clave",
    # En el PDF digital, clave, nombre y entidad se toman de la capa de texto (reglas_curp.
    # datos_texto_constancia); lo leído por Gemini se compara y, si difiere, se revisa.
    "campos_desde_texto": True,
    # La constancia oficial trae exactamente 4 imágenes embebidas (encabezado, 2 QR y barras) en
    # los dos modelos vistos. Una más suele ser una marca de agua de una app (p. ej. CamScanner)
    # o una edición: pasa a revisar. Ajustar si aparece un modelo con más imágenes.
    "max_imagenes_embebidas": 4,
    # Fracción de la 1.ª página en blanco exacto (ver captura.blanco_puro), solo si el PDF tiene texto.
    # Medido: 13 constancias válidas 0,739-0,774; escaneos 0,23-0,68. 0,70 queda en el hueco con margen a
    # ambos lados. Debajo -> revisar (no rechazar: una constancia válida con más texto baja el valor).
    "umbral_blanco_puro": 0.70,
    # Metadatos del sistema que genera la constancia: las 13 válidas los traen idénticos; las no válidas,
    # 'iLovePDF', 'intsig.com' (CamScanner) o vacío. No coincidir -> revisar (si RENAPO cambia de
    # generador, todas fallarían: por eso no rechaza).
    "huella_origen": {
        "productor": "iText",          # el productor debe empezar así
        "creador": "JasperReports",    # el creador debe empezar así
        "sin_modificaciones": True,    # fecha de modificación igual a la de creación
    },
    "checks": {
        "leyenda_estados_unidos_mexicanos": {
            "nivel": "critico",
            "descripcion": "Encabezado con el texto 'ESTADOS UNIDOS MEXICANOS' y el escudo nacional",
            "patrones": ["ESTADOS UNIDOS MEXICANOS"],
        },
        "leyenda_constancia_curp": {
            "nivel": "critico",
            "descripcion": "Texto 'CONSTANCIA DE LA CLAVE ÚNICA DE REGISTRO DE POBLACIÓN'",
            "patrones": ["CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION"],
        },
        "etiqueta_clave": {
            "nivel": "critico",
            "descripcion": "Etiqueta 'Clave:' seguida de la CURP en letra grande",
            "patrones": ["CLAVE:"],
        },
        "codigo_qr": {
            "nivel": "critico",
            "descripcion": "Código QR en la parte superior derecha de la primera hoja",
        },
        "etiqueta_nombre": {
            "nivel": "importante",
            "descripcion": "Etiqueta 'Nombre' seguida del nombre completo",
            "patrones": ["NOMBRE"],
        },
        "entidad_de_registro": {
            "nivel": "importante",
            "descripcion": "Texto 'Entidad de registro:' con el nombre de la entidad",
            "patrones": ["ENTIDAD DE REGISTRO"],
        },
        # Hay dos modelos de constancia válidos: el actual (pie con 'Gobierno de México',
        # 'Gobernación' y 'RENAPO') y el anterior (logo 'SEGOB' en el encabezado). Que estén
        # los logos no determina la validez: solo se informa.
        "logos_institucionales": {
            "nivel": "opcional",
            "descripcion": "Logos institucionales: 'SEGOB' en el encabezado (modelo anterior) o 'Gobierno de México', 'Gobernación' y 'RENAPO' en el pie (modelo actual)",
        },
        "bandera_mexico": {
            "nivel": "importante",
            "descripcion": "Bandera de México junto al texto 'Soy México'",
        },
        "codigo_barras": {
            "nivel": "importante",
            "descripcion": "Código de barras con un número debajo, en la parte inferior izquierda de la primera hoja",
        },
        # Redactado en positivo como el resto: presente=true significa que NO hay marcas ajenas.
        "sin_marcas_de_terceros": {
            "nivel": "critico",
            "descripcion": "El documento está libre de marcas de agua o logotipos de aplicaciones de terceros (p. ej. CamScanner, Adobe Scan, WPS, iLovePDF, Smallpdf); solo figuran los elementos oficiales",
            "mensaje_si_falta": "Tiene una marca de agua o logotipo de una aplicación de terceros: el archivo fue procesado con otra aplicación y no es el original",
        },
        # La 2.ª hoja (carta) puede no subirse: solo informamos.
        "carta_presente_secretaria": {
            "nivel": "opcional",
            "descripcion": "Segunda hoja: carta que empieza con 'PRESENTE' y está firmada por la Secretaría de Gobernación",
            "patrones": ["PRESENTE"],
        },
        "leyenda_telcurp": {
            "nivel": "opcional",
            "descripcion": "Segunda hoja: texto 'TELCURP' con el teléfono 800 911 11 11",
            "patrones": ["TELCURP"],
        },
        "leyenda_tramite_gratuito": {
            "nivel": "opcional",
            "descripcion": "Segunda hoja: leyenda 'TRÁMITE GRATUITO'",
            "patrones": ["TRAMITE GRATUITO"],
        },
    },
}

# Criterios definidos con 6 ejemplos reales (todos con QR; varios son escaneos de la versión
# impresa). Aún sin ejemplos negativos (falsos/adulterados) para calibrar. Con `provisorio` en
# True el resultado nunca es "aceptado": como máximo "revisar".
CERTIFICADO_BACHILLERATO = {
    "nombre": "Certificado de bachillerato (digital / semielectrónico)",
    "nombre_corto": "certificado de bachillerato",
    "articulo": "el",
    "provisorio": False,
    "requiere_pdf_digital": False,
    "campos": {
        "nombre_alumno": "Nombre completo del alumno",
        "institucion": "Nombre de la institución educativa que emite el certificado",
        "curp": "CURP del alumno, si figura en el documento",
        "folio": "Folio o número de certificado, si figura",
        "promedio": "Promedio general, si figura",
        "fecha_expedicion": "Fecha de expedición, si figura",
        "enlace_verificacion_impreso": "URL de verificación impresa en el documento como texto (p. ej. tras 'o en:'), transcrita completa y tal como figura; null si no hay ninguna",
    },
    "campo_clave": "curp",
    "checks": {
        "institucion_legible": {
            "nivel": "critico",
            "descripcion": "El nombre de la institución emisora es legible",
        },
        "leyenda_certificado": {
            "nivel": "critico",
            "descripcion": "El documento se identifica como certificado de terminación de estudios / bachillerato",
            "patrones": ["CERTIFICADO"],
        },
        "nombre_alumno_legible": {
            "nivel": "critico",
            "descripcion": "El nombre del alumno es legible",
        },
        # Tanto el certificado electrónico como el semielectrónico llevan QR de verificación.
        "codigo_qr": {
            "nivel": "critico",
            "descripcion": "Código QR de verificación del certificado (suele estar abajo a la izquierda de la primera hoja)",
        },
        # Elementos propios de cada variante. Son opcionales a nivel de check: lo que se espera
        # de cada variante está en `reglas_variante` (más abajo) y su ausencia lleva a "revisar".
        "firma_autografa": {
            "nivel": "opcional",
            "descripcion": "Firma manuscrita (autógrafa) de una autoridad o directivo sobre el documento: trazo de tinta, no texto tipografiado",
        },
        "sello_o_firma_electronica": {
            "nivel": "opcional",
            "descripcion": "Sello digital, cadena original o firma electrónica impresos (bloques largos de caracteres alfanuméricos, p. ej. 'Sello digital autoridad educativa' o 'Sello digital SEP')",
            "patrones": ["SELLO DIGITAL", "CADENA ORIGINAL", "FIRMA ELECTRONICA"],
        },
        "sello_institucional": {
            "nivel": "opcional",
            "descripcion": "Sello oficial estampado de la institución o autoridad educativa (impresión de sello de tinta o relieve), distinto de un sello digital",
        },
        "foto_del_alumno": {
            "nivel": "opcional",
            "descripcion": "Fotografía (retrato) del alumno",
        },
        "folio_visible": {
            "nivel": "opcional",
            "descripcion": "Folio o número de certificado visible",
            "patrones": ["FOLIO"],
        },
    },
    # Qué se espera de cada variante (checks de arriba). Falta un esperado, o hay uno que no
    # corresponde -> revisar. Provisorio: calibrar con ejemplos etiquetados y negativos.
    "reglas_variante": {
        "semielectronico": {"esperados": ["firma_autografa"], "no_esperados": []},
        "electronico": {"esperados": ["sello_o_firma_electronica"], "no_esperados": ["firma_autografa", "foto_del_alumno"]},
    },
    # Dominios a los que apunta el QR de un certificado real (host exacto). Salen de los ejemplos
    # reales recibidos: ampliar al ver otros sistemas. Un QR que apunte a otro dominio -> revisar.
    "qr_dominios": {
        "www.pace.sep.gob.mx",
        "siseems.sems.gob.mx",
        "www.acuerdo286.sep.gob.mx",
        "siged.sep.gob.prepa-enlinea.mx",  # OJO: no es *.gob.mx; confirmar que es oficial
    },
    "variantes": {
        "electronico": "Certificado electrónico: formato variable, sin fotografía ni firmas manuscritas; con sellos y firmas electrónicos (cadena original, sello digital) y código QR",
        "semielectronico": "Certificado semielectrónico: formato variable, con firma autógrafa (manuscrita), puede traer o no fotografía; con código QR",
        "no_reconocido": "No se puede asignar a ninguna de las anteriores",
    },
}

DOCUMENTOS = {
    "curp": CURP,
    "certificado_bachillerato": CERTIFICADO_BACHILLERATO,
}
