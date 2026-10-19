import io

import pypdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

import movil


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(movil, "almacen", movil.AlmacenLocal(tmp_path))
    app = FastAPI()
    app.include_router(movil.router)
    return TestClient(app)


def _foto(ancho=300, alto=400, formato="JPEG") -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(salida, formato)
    return salida.getvalue()


def _subir(cliente, id_, fotos, tipo="image/jpeg"):
    return cliente.post(f"/movil/{id_}/fotos", files=[("files", (f"f{i}.jpg", f, tipo)) for i, f in enumerate(fotos)])


def test_recorrido_completo_varias_fotos_en_un_pdf(cliente):
    id_ = cliente.post("/movil/sesiones").json()["id"]
    assert cliente.get(f"/movil/{id_}/estado").json()["estado"] == "pendiente"

    assert _subir(cliente, id_, [_foto(), _foto(ancho=500, formato="PNG")]).json() == {"estado": "listo", "paginas": 2}
    assert cliente.get(f"/movil/{id_}/estado").json()["estado"] == "listo"

    resp = cliente.get(f"/movil/{id_}/documento")
    assert resp.headers["content-type"] == "application/pdf"
    assert len(pypdf.PdfReader(io.BytesIO(resp.content)).pages) == 2

    # Se entrega una sola vez y la sesión no acepta más fotos.
    assert cliente.get(f"/movil/{id_}/documento").status_code == 404
    assert _subir(cliente, id_, [_foto()]).status_code == 409


def test_la_pagina_del_celular_se_sirve(cliente):
    id_ = cliente.post("/movil/sesiones").json()["id"]
    assert "text/html" in cliente.get(f"/movil/{id_}").headers["content-type"]


def test_sesion_inexistente_o_vencida(cliente, monkeypatch):
    assert cliente.get("/movil/no-existe-esta-sesion-xyz/estado").status_code == 404
    assert cliente.get("/movil/..%2F..%2Fetc/estado").status_code == 404
    id_ = cliente.post("/movil/sesiones").json()["id"]
    monkeypatch.setattr(movil.time, "time", lambda: 10**12)
    assert cliente.get(f"/movil/{id_}/estado").status_code == 410


def test_rechaza_lo_que_no_es_foto_y_el_exceso_de_fotos(cliente):
    id_ = cliente.post("/movil/sesiones").json()["id"]
    assert _subir(cliente, id_, [b"%PDF-1.4"], tipo="application/pdf").status_code == 415
    assert _subir(cliente, id_, [_foto()] * (movil.MAX_PAGINAS + 1)).status_code == 400
    assert _subir(cliente, id_, [b"no es una imagen"]).status_code == 422
    assert cliente.get(f"/movil/{id_}/estado").json()["estado"] == "pendiente"


def test_respeta_la_orientacion_de_la_camara():
    salida = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # rotada 90°: el celular la guardó acostada
    Image.new("RGB", (400, 300), "white").save(salida, "JPEG", exif=exif)
    pagina = pypdf.PdfReader(io.BytesIO(movil.fotos_a_pdf([salida.getvalue()]))).pages[0]
    assert pagina.mediabox.height > pagina.mediabox.width
