"""Captura con el celular (solo certificado): la computadora muestra un QR, el celular saca las fotos.

Recorrido:
1. La computadora crea una sesión (`POST /movil/sesiones`) y muestra un QR con la URL `/movil/{id}`.
2. El celular abre esa página (detrás de IAP, como el resto), saca una o varias fotos y las sube
   (`POST /movil/{id}/fotos`). Se juntan en un PDF, una página por foto.
3. La computadora consulta `GET /movil/{id}/estado`; cuando está `listo`, baja el PDF
   (`GET /movil/{id}/documento`, que lo borra) y lo manda a `/validar` como un archivo local.

Las sesiones viven en un almacén compartido entre instancias de Cloud Run: un bucket de Cloud Storage
(`MOVIL_BUCKET`, con borrado automático por antigüedad) o, en local, una carpeta temporal.
"""
import io
import json
import os
import re
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image, ImageOps

from composicion import MAX_PAGINAS

router = APIRouter(prefix="/movil", tags=["captura con el celular"])

VIGENCIA_S = 15 * 60
MAX_BYTES = 20 * 1024 * 1024  # mismo límite que /validar
TIPOS_IMAGEN = {"image/jpeg", "image/png"}
_ID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


class AlmacenLocal:
    def __init__(self, carpeta: Path):
        self.carpeta = carpeta

    def leer(self, nombre: str) -> bytes | None:
        ruta = self.carpeta / nombre
        return ruta.read_bytes() if ruta.exists() else None

    def escribir(self, nombre: str, datos: bytes) -> None:
        ruta = self.carpeta / nombre
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)

    def borrar(self, nombre: str) -> None:
        (self.carpeta / nombre).unlink(missing_ok=True)


class AlmacenGCS:
    def __init__(self, bucket: str):
        from google.cloud import storage

        self.bucket = storage.Client().bucket(bucket)

    def leer(self, nombre: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        try:
            return self.bucket.blob(nombre).download_as_bytes()
        except NotFound:
            return None

    def escribir(self, nombre: str, datos: bytes) -> None:
        self.bucket.blob(nombre).upload_from_string(datos)

    def borrar(self, nombre: str) -> None:
        from google.api_core.exceptions import NotFound

        try:
            self.bucket.blob(nombre).delete()
        except NotFound:
            pass


almacen = (AlmacenGCS(os.environ["MOVIL_BUCKET"]) if os.environ.get("MOVIL_BUCKET")
           else AlmacenLocal(Path(tempfile.gettempdir()) / "validador-movil"))


def _estado(id_: str) -> dict:
    """Estado de una sesión vigente; 404 si no existe, 410 si venció."""
    if not _ID.match(id_):
        raise HTTPException(404, "Sesión inexistente")
    crudo = almacen.leer(f"{id_}/estado.json")
    if crudo is None:
        raise HTTPException(404, "Sesión inexistente")
    estado = json.loads(crudo)
    if time.time() > estado["vence"]:
        raise HTTPException(410, "La sesión venció. Generá un QR nuevo desde la computadora.")
    return estado


def _guardar_estado(id_: str, estado: dict) -> None:
    almacen.escribir(f"{id_}/estado.json", json.dumps(estado).encode())


def fotos_a_pdf(fotos: list[bytes]) -> bytes:
    """Una página por foto, en el orden recibido. Respeta la orientación EXIF del celular."""
    paginas = [ImageOps.exif_transpose(Image.open(io.BytesIO(f))).convert("RGB") for f in fotos]
    salida = io.BytesIO()
    paginas[0].save(salida, "PDF", save_all=True, append_images=paginas[1:], resolution=200)
    return salida.getvalue()


@router.post("/sesiones")
def crear_sesion():
    id_ = secrets.token_urlsafe(24)
    estado = {"estado": "pendiente", "vence": time.time() + VIGENCIA_S, "paginas": 0}
    _guardar_estado(id_, estado)
    return {"id": id_, "url": f"movil/{id_}", "vence_en_s": VIGENCIA_S, "max_fotos": MAX_PAGINAS}


@router.get("/{id_}", include_in_schema=False)
def pagina_movil(id_: str):
    """Página para el celular; la validez de la sesión la consulta ella misma."""
    return FileResponse(Path(__file__).with_name("movil.html"))


@router.get("/{id_}/estado")
def consultar_estado(id_: str):
    estado = _estado(id_)
    return {"estado": estado["estado"], "paginas": estado["paginas"], "max_fotos": MAX_PAGINAS,
            "vence_en_s": max(0, int(estado["vence"] - time.time()))}


@router.post("/{id_}/fotos")
def subir_fotos(id_: str, files: list[UploadFile] = File(...)):
    estado = _estado(id_)
    if estado["estado"] != "pendiente":
        raise HTTPException(409, "Las fotos de esta sesión ya se enviaron.")
    if len(files) > MAX_PAGINAS:
        raise HTTPException(400, f"Máximo {MAX_PAGINAS} fotos.")
    fotos, total = [], 0
    for f in files:
        if f.content_type not in TIPOS_IMAGEN:
            raise HTTPException(415, "Solo se aceptan fotos JPG o PNG.")
        datos = f.file.read()
        total += len(datos)
        if total > MAX_BYTES:
            raise HTTPException(413, "Las fotos pesan demasiado (máx. 20 MB en total).")
        fotos.append(datos)
    try:
        pdf = fotos_a_pdf(fotos)
    except Exception as e:
        print(f"Fotos ilegibles en la sesión {id_}: {e}")
        raise HTTPException(422, "No se pudo leer alguna de las fotos. Probá sacarla de nuevo.")
    almacen.escribir(f"{id_}/documento.pdf", pdf)
    _guardar_estado(id_, {**estado, "estado": "listo", "paginas": len(fotos)})
    return {"estado": "listo", "paginas": len(fotos)}


@router.get("/{id_}/documento")
def bajar_documento(id_: str):
    """Entrega el PDF armado una sola vez: después se borra y la sesión queda cerrada."""
    estado = _estado(id_)
    pdf = almacen.leer(f"{id_}/documento.pdf") if estado["estado"] == "listo" else None
    if pdf is None:
        raise HTTPException(404, "Todavía no hay fotos en esta sesión.")
    almacen.borrar(f"{id_}/documento.pdf")
    _guardar_estado(id_, {**estado, "estado": "entregado"})
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="certificado-celular.pdf"'})
