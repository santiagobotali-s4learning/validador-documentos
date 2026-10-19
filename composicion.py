"""¿Qué documentos trae un PDF de varias páginas?

Un alumno puede subir en un mismo PDF varios documentos (caso real: acta de nacimiento + certificado
+ constancia de CURP, unidos con iLovePDF). Se identifica qué hay en cada página, se analiza solo el
documento que se pidió validar y, si además hay otros, el resultado es "rechazado" (decision.evaluar).

Cada página se identifica con la misma prioridad que el resto del sistema:
  código (QR o texto del PDF con un formato inconfundible) > Gemini.
Las páginas que Gemini marca como continuación (reverso, 2.ª hoja) se suman al documento anterior, para
que un certificado de 2 páginas no cuente como 2 documentos.
"""
import io
from urllib.parse import urlparse

import pypdf

import captura
import reglas_curp
from config_documentos import DOCUMENTOS

MAX_PAGINAS = 10

# Textos que, en la capa de texto de una página, identifican el documento sin dudas (normalizados:
# mayúsculas, sin acentos). Solo existen en PDF digitales: en un escaneo decide el QR o Gemini.
TEXTOS_INCONFUNDIBLES = {
    "curp": ["CONSTANCIA DE LA CLAVE UNICA DE REGISTRO DE POBLACION"],
    "certificado_bachillerato": ["CERTIFICADO DE TERMINACION DE ESTUDIOS", "CERTIFICADO DE BACHILLERATO"],
}


def contar_paginas(contents: bytes) -> int:
    return len(pypdf.PdfReader(io.BytesIO(contents)).pages)


def senales(contents: bytes) -> list[dict]:
    """Por página: texto normalizado y QR leídos (sin IA)."""
    lector = pypdf.PdfReader(io.BytesIO(contents))
    textos = [captura.normalizar(p.extract_text() or "") for p in lector.pages[:MAX_PAGINAS]]
    imagenes = captura.renderizar(contents, "application/pdf", max_paginas=MAX_PAGINAS)
    qrs, _ = captura.qr_por_pagina(contents, "application/pdf", imagenes)
    return [{"texto": t, "qr": q} for t, q in zip(textos, qrs)]


def tipo_por_codigo(texto: str, qrs: list[str]) -> tuple[str | None, str | None]:
    """(tipo, evidencia) si el QR o el texto de la página identifican el documento sin dudas."""
    for contenido in qrs:
        if reglas_curp.datos_qr_curp(contenido):
            return "curp", "QR con los datos de una constancia de CURP"
        if contenido.lower().startswith(("http://", "https://")):
            host = urlparse(contenido).hostname
            if host in DOCUMENTOS["certificado_bachillerato"].get("qr_dominios", set()):
                return "certificado_bachillerato", f"QR de verificación de certificado ({host})"
    for tipo, frases in TEXTOS_INCONFUNDIBLES.items():
        hallada = next((f for f in frases if f in texto), None)
        if hallada:
            return tipo, f"texto '{hallada}'"
    return None, None


def combinar(por_codigo: list[dict], del_modelo: list[dict]) -> list[dict]:
    """Une la identificación por código (por página) con la de Gemini.

    Prioridad por página: código > continuación del documento anterior (según Gemini) > tipo según Gemini.
    """
    modelo = {p.get("pagina"): p for p in del_modelo}
    resultado: list[dict] = []
    for numero, pagina in enumerate(por_codigo, start=1):
        visto = modelo.get(numero, {})
        tipo, evidencia = tipo_por_codigo(pagina["texto"], pagina["qr"])
        if tipo:
            fuente = "codigo"
        elif visto.get("continuacion") and resultado:
            tipo, fuente, evidencia = resultado[-1]["documento"], "continuacion", "continúa el documento de la página anterior"
        elif visto.get("documento"):
            tipo, fuente = visto["documento"], "gemini"
        else:  # Gemini no informó esta página: se asume que sigue el documento anterior
            tipo, fuente = (resultado[-1]["documento"] if resultado else "otro"), "sin_dato"
        if tipo in DOCUMENTOS:
            nombre = DOCUMENTOS[tipo]["nombre_corto"]
        else:
            nombre = visto.get("descripcion") or "documento no identificado"
        resultado.append({"pagina": numero, "documento": tipo, "descripcion": nombre,
                          "fuente": fuente, "evidencia": evidencia})
    return resultado


def paginas_de(composicion: list[dict], tipo: str) -> list[int]:
    return [p["pagina"] for p in composicion if p["documento"] == tipo]


def otros_documentos(composicion: list[dict], tipo: str) -> list[str]:
    """'acta de nacimiento (pág. 1)', agrupando páginas seguidas del mismo documento."""
    grupos: list[list] = []
    for p in composicion:
        if p["documento"] == tipo:
            continue
        if grupos and grupos[-1][0] == p["descripcion"] and grupos[-1][2] == p["pagina"] - 1:
            grupos[-1][2] = p["pagina"]
        else:
            grupos.append([p["descripcion"], p["pagina"], p["pagina"]])
    return [f"{d} (pág. {a})" if a == b else f"{d} (págs. {a}-{b})" for d, a, b in grupos]


def extraer_paginas(contents: bytes, paginas: list[int]) -> bytes:
    """Un PDF solo con esas páginas (numeradas desde 1), conservando los metadatos del original."""
    lector = pypdf.PdfReader(io.BytesIO(contents))
    escritor = pypdf.PdfWriter()
    for numero in paginas:
        escritor.add_page(lector.pages[numero - 1])
    if lector.metadata:
        escritor.add_metadata({k: v for k, v in lector.metadata.items() if isinstance(v, str)})
    salida = io.BytesIO()
    escritor.write(salida)
    return salida.getvalue()
