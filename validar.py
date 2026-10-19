import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import captura
import composicion
import motor_gemini
from config_documentos import DOCUMENTOS
from decision import evaluar

app = FastAPI(title="Validación de formato de documentos (Gemini)")

TIPOS_PERMITIDOS = {"application/pdf", "image/png", "image/jpeg"}
MAX_BYTES = 20 * 1024 * 1024
# Solo para pruebas: tratar una imagen como "revisar" en vez de "rechazado" en documentos que exigen PDF.
ACEPTAR_IMAGENES = os.environ.get("ACEPTAR_IMAGENES") == "1"

# Para sumar Document AI: crear un motor con el mismo contrato (ver motor_documentai.py)
# y elegirlo aquí por tarea.
MOTOR = motor_gemini


@app.get("/", include_in_schema=False)
def interfaz():
    """Página de pruebas manuales (misma origen que la API, sin CORS)."""
    return FileResponse(Path(__file__).with_name("interfaz.html"))


@app.get("/health")
def health():
    return {"status": "ok", "modo": motor_gemini.MODO, "modelo": motor_gemini.GEMINI_MODEL}


@app.get("/tipos")
def tipos():
    return {k: {"nombre": v["nombre"], "provisorio": v.get("provisorio", False)} for k, v in DOCUMENTOS.items()}


@app.post("/validar")
def validar(
    file: UploadFile = File(...),
    tipo: str | None = Form(None, description=f"Tipo esperado: {', '.join(DOCUMENTOS)}. Si se omite, se clasifica."),
):
    if file.content_type not in TIPOS_PERMITIDOS:
        raise HTTPException(415, f"Tipo de archivo no soportado. Permitidos: {sorted(TIPOS_PERMITIDOS)}")
    contents = file.file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(413, "Archivo demasiado grande (máx. 20 MB)")
    if tipo is not None and tipo not in DOCUMENTOS:
        raise HTTPException(400, f"Tipo desconocido. Opciones: {list(DOCUMENTOS)}")

    es_pdf = file.content_type == "application/pdf"
    try:
        paginas = composicion.contar_paginas(contents) if es_pdf else 1
        # PDF de varias páginas: puede traer varios documentos juntos (ver composicion.py)
        senales = composicion.senales(contents) if 1 < paginas <= composicion.MAX_PAGINAS else None
    except Exception as e:
        print(f"Archivo ilegible {file.filename}: {e}")
        raise HTTPException(422, "No se pudo leer el archivo. Verificá que no esté dañado.")
    if paginas > composicion.MAX_PAGINAS:
        return _rechazo(file.filename, tipo, [
            f"El archivo tiene {paginas} páginas (máximo {composicion.MAX_PAGINAS}). Subí solo el documento pedido."
        ])

    # 1) ¿Qué documento hay y en qué páginas?
    analizado, comp = contents, None
    try:
        if senales is not None:
            comp = composicion.combinar(senales, MOTOR.clasificar_paginas(contents, file.content_type, paginas))
            if tipo is None:
                presentes = list(dict.fromkeys(p["documento"] for p in comp))
                if len(presentes) > 1:
                    return _rechazo(file.filename, None, [
                        "El archivo trae varios documentos: " + ", ".join(composicion.otros_documentos(comp, "")) +
                        ". Elegí el tipo esperado o subí un archivo por documento."
                    ], comp)
                tipo = presentes[0]
            elif not composicion.paginas_de(comp, tipo):
                return _rechazo(file.filename, tipo, [
                    f"No se encontró {DOCUMENTOS[tipo]['articulo']} {DOCUMENTOS[tipo]['nombre_corto']} en el archivo "
                    f"(se detectó: {', '.join(composicion.otros_documentos(comp, tipo))})."
                ], comp)
        elif tipo is None:
            tipo = MOTOR.clasificar(contents, file.content_type)
        if tipo == "otro":
            return _rechazo(file.filename, None, ["El documento no corresponde a ninguno de los tipos admitidos."], comp)
    except Exception as e:
        raise _error_del_motor(file.filename, e)

    # Se analizan solo las páginas del documento pedido.
    if comp and len(composicion.paginas_de(comp, tipo)) < paginas:
        analizado = composicion.extraer_paginas(contents, composicion.paginas_de(comp, tipo))

    # 2) Análisis por código y 3) lectura con Gemini, sobre esas páginas
    try:
        info = captura.analizar(analizado, file.content_type)
    except Exception as e:
        print(f"Archivo ilegible {file.filename}: {e}")
        raise HTTPException(422, "No se pudo leer el archivo. Verificá que no esté dañado.")
    try:
        gem = MOTOR.analizar(analizado, file.content_type, tipo)
    except Exception as e:
        raise _error_del_motor(file.filename, e)

    # 4) Decisión
    return {"archivo": file.filename, **evaluar(tipo, info, gem, ACEPTAR_IMAGENES, composicion=comp)}


def _rechazo(archivo: str, tipo: str | None, motivos: list[str], comp: list[dict] | None = None) -> dict:
    return {"archivo": archivo, "tipo": tipo or "otro", "resultado": "rechazado", "motivos": motivos,
            "composicion": comp}


def _error_del_motor(archivo: str, e: Exception) -> HTTPException:
    print(f"Error del motor procesando {archivo}: {e}")  # al log, no al cliente
    if getattr(e, "code", None) == 429:  # cuota de Gemini agotada: transitorio, se puede reintentar
        return HTTPException(
            503, "El servicio de análisis está saturado. Reintentá en unos segundos.",
            headers={"Retry-After": "30"},
        )
    return HTTPException(502, "Error al analizar el documento")
