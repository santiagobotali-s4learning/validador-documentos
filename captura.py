"""Análisis determinista del archivo: ¿es un PDF digital original, o un escaneo/foto?

Señales (ninguna es infalible por sí sola, por eso se devuelven todas):
  - capa de texto: un PDF generado por un sistema trae texto real; un escaneo es una imagen.
  - imágenes embebidas: un escaneo es (casi siempre) una imagen a página completa.
  - blanco puro: un documento digital tiene grandes zonas de blanco exacto (255); en un
    escaneo o foto el papel nunca es 255 uniforme (ruido, sombras, gradientes).
    OJO: se descartó medir el "ruido del fondo claro" porque las marcas de agua y el diseño
    decorativo de la propia constancia (CURP) lo disparaban en documentos 100 % digitales.
"""
import io
import itertools
import re
import time
import unicodedata

import cv2
import numpy as np
import pypdf
import pypdfium2 as pdfium

MIN_CHARS_TEXTO = 50
# Piso grueso de píxeles en blanco exacto para considerar "digital" (debajo -> rechazado). Muy bajo a
# propósito: las apps de escaneo blanquean el fondo (escaneos reales dieron 0,62-0,68), así que no los
# separa; el umbral fino, por tipo de documento y con "revisar", está en config_documentos.
UMBRAL_BLANCO_PURO = 0.10
# Escalas extra (además de la 2 con que se renderiza la página) para leer QR chicos o de escaneo.
ESCALAS_QR_EXTRA = (3, 4)
# Tope de píxeles del lado mayor al renderizar una página: sin él, una página grande a escala 4
# más los preprocesados agotan la memoria del contenedor (pasó con un escaneo de 612x1008 pt).
LADO_MAX_PX = 3200
# Tiempo máximo para leer QR en un archivo: si no se lee, se informa como detectado/no legible.
SEGUNDOS_MAX_QR = 25


def normalizar(texto: str) -> str:
    """Mayúsculas, sin acentos y con espacios colapsados, para comparar leyendas."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto).upper().strip()
    return re.sub(r"\s+:", ":", texto)


def _render(pdf, indice: int, escala: float) -> np.ndarray:
    ancho, alto = pdf[indice].get_size()
    escala = min(escala, LADO_MAX_PX / max(ancho, alto))
    rgb = np.array(pdf[indice].render(scale=escala).to_pil().convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def renderizar(contents: bytes, mime: str, max_paginas: int = 2) -> list[np.ndarray]:
    """Devuelve las primeras páginas (o la imagen) como arreglos BGR."""
    if mime == "application/pdf":
        pdf = pdfium.PdfDocument(contents)
        return [_render(pdf, i, 2) for i in range(min(len(pdf), max_paginas))]
    img = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []
    lado = max(img.shape[:2])
    if lado > LADO_MAX_PX:
        img = cv2.resize(img, None, fx=LADO_MAX_PX / lado, fy=LADO_MAX_PX / lado, interpolation=cv2.INTER_AREA)
    return [img]


def blanco_puro(imagen: np.ndarray) -> float:
    """Fracción de píxeles en blanco exacto (255). Alta en digital, ~0 en escaneo o foto."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    return round(float((gris == 255).mean()), 3)


def _variantes_qr(img: np.ndarray):
    """La misma imagen tratada de cuatro formas: un QR de escaneo (borroso, con textura y poco
    contraste) suele leerse con una y fallar con otra, y cuál sirve cambia de un archivo a otro."""
    gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    borroso = cv2.GaussianBlur(gris, (0, 0), 1.2)
    yield img
    yield cv2.addWeighted(gris, 1.8, borroso, -0.8, 0)  # nitidez
    yield cv2.createCLAHE(3.0, (8, 8)).apply(gris)  # contraste local
    yield cv2.adaptiveThreshold(borroso, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 10)


def _leer_qr(img: np.ndarray, detectores) -> tuple[list[str], int]:
    """(textos leídos, QR detectados) en una imagen. Prueba cada detector hasta leer algo.

    El detector ArUco busca varios QR a la vez. El clásico solo se usa de a UNO: en modo "varios"
    combina todos los candidatos a esquina de QR y, sobre un fondo de seguridad con tramas (caso real:
    un acta de nacimiento escaneada), tardó 140 s y pasó los 2 GiB de memoria, tumbando el contenedor.
    De a uno tarda 0,1 s en la misma imagen.
    """
    detectados = 0
    for detector in detectores:
        try:
            if isinstance(detector, cv2.QRCodeDetectorAruco):
                ok, textos, puntos, _ = detector.detectAndDecodeMulti(img)
            else:
                texto, puntos, _ = detector.detectAndDecode(img)
                ok, textos = True, [texto]
                puntos = None if puntos is None else puntos.reshape(1, -1, 2)
        except cv2.error:
            continue
        detectados = max(detectados, len(puntos) if puntos is not None else 0)
        leidos = [t for t in textos if t] if ok else []
        if leidos:
            return leidos, detectados
    return [], detectados


def decodificar_qr(contents: bytes, mime: str, paginas: list[np.ndarray]) -> tuple[list[str], int]:
    """Devuelve (contenidos leídos, cantidad de QR detectados aunque no se hayan podido leer).

    Cada página se prueba a varias resoluciones y con varios preprocesados, y se corta en cuanto
    se lee algo. En los escaneos el QR ocupa pocos píxeles: a la resolución normal se detecta pero
    no se decodifica, y renderizar el PDF de nuevo a mayor escala (no agrandar la imagen ya
    renderizada) es lo que lo recupera. Detector ArUco de OpenCV primero (más fiable en página
    completa) y el clásico como respaldo.
    """
    por_pagina, detectados = qr_por_pagina(contents, mime, paginas)
    return list(dict.fromkeys(t for leidos in por_pagina for t in leidos)), detectados


def qr_por_pagina(contents: bytes, mime: str, paginas: list[np.ndarray]) -> tuple[list[list[str]], int]:
    """Como decodificar_qr, pero con lo leído en cada página por separado."""
    detectores = [cv2.QRCodeDetectorAruco(), cv2.QRCodeDetector()]
    pdf = pdfium.PdfDocument(contents) if mime == "application/pdf" else None
    por_pagina, detectados = [], 0
    limite = time.monotonic() + SEGUNDOS_MAX_QR
    for i, base in enumerate(paginas):
        # Las capturas de pantalla (imagen suelta, chica) se agrandan por interpolación.
        if pdf is not None:
            # Generador: las escalas altas solo se renderizan si las anteriores no leyeron nada.
            niveles = itertools.chain([base], (_render(pdf, i, e) for e in ESCALAS_QR_EXTRA))
        else:
            niveles = [base] + ([cv2.resize(base, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)] if base.shape[1] < 1500 else [])
        en_pagina, leidos = 0, []
        for nivel in niveles:
            for variante in _variantes_qr(nivel):
                leidos, n = _leer_qr(variante, detectores)
                en_pagina = max(en_pagina, n)
                if leidos or time.monotonic() > limite:
                    break
            if leidos or time.monotonic() > limite:
                break
        por_pagina.append(leidos)
        detectados += max(en_pagina, len(leidos))
    return por_pagina, detectados


def hay_codigo_barras(imagenes: list[np.ndarray]) -> bool:
    """Detecta (sin leer) un código de barras lineal. Ver también el check visual de Gemini."""
    detector = cv2.barcode_BarcodeDetector()
    for img in imagenes:
        try:
            ok, _ = detector.detect(img)[:2]
        except cv2.error:
            continue
        if ok:
            return True
    return False


# Cómo se le envía un PDF a Gemini (ver motor_gemini): con texto -> imágenes; sin texto (escaneo) -> PDF.
ESCALA_ENVIO_PDF = 3
PAGINAS_ENVIO_PDF = 2


def tiene_capa_de_texto(contents: bytes) -> bool:
    try:
        lector = pypdf.PdfReader(io.BytesIO(contents))
        texto = "".join((p.extract_text() or "") for p in lector.pages[:PAGINAS_ENVIO_PDF])
    except Exception:
        return False
    return len(texto.strip()) >= MIN_CHARS_TEXTO


def envio_a_gemini(contents: bytes, mime: str, pdf_como_imagen: bool = True) -> list[tuple[bytes, str]]:
    """[(bytes, mime)] que se adjuntan al prompt.

    Un PDF con capa de texto (digital, vectorial: la constancia de CURP) se envía como imágenes de
    sus primeras páginas: con el PDF original Gemini lo rasteriza a baja resolución y lee mal los
    textos chicos (transcribió una CURP de 18 caracteres como 'EARH050dYA8' en 5 de 5 intentos;
    renderizada a escala 3 la leyó bien en 4 de 4). Un PDF sin texto (escaneo: los certificados)
    se envía tal cual: Gemini toma la imagen embebida a su resolución original, mejor que la que
    se obtiene al renderizar la página (medido: renderizado, perdía la CURP en 2 de 2 intentos y
    se inventaba el enlace impreso).
    """
    if mime == "application/pdf" and pdf_como_imagen and tiene_capa_de_texto(contents):
        pdf = pdfium.PdfDocument(contents)
        paginas = [_render(pdf, i, ESCALA_ENVIO_PDF) for i in range(min(len(pdf), PAGINAS_ENVIO_PDF))]
        if paginas:
            return [(cv2.imencode(".png", p)[1].tobytes(), "image/png") for p in paginas]
    return [(contents, mime)]


def analizar(contents: bytes, mime: str) -> dict:
    paginas = renderizar(contents, mime)
    blanco = blanco_puro(paginas[0]) if paginas else None
    qr, qr_detectados = decodificar_qr(contents, mime, paginas)
    info = {
        "formato": "pdf" if mime == "application/pdf" else "imagen",
        "blanco_puro": blanco,
        "texto": "",
        "caracteres_texto": 0,
        "imagenes_embebidas": 0,
        "lineas_texto": [],
        "productor": None,
        "creador": None,
        "fecha_creacion": None,
        "fecha_modificacion": None,
        "paginas": len(paginas),
        "qr": qr,
        "qr_detectados": qr_detectados,
        "codigo_barras": hay_codigo_barras(paginas),
    }

    if mime == "application/pdf":
        lector = pypdf.PdfReader(io.BytesIO(contents))
        info["paginas"] = len(lector.pages)
        meta = lector.metadata or {}
        info["productor"] = meta.get("/Producer")
        info["creador"] = meta.get("/Creator")
        info["fecha_creacion"] = meta.get("/CreationDate")
        info["fecha_modificacion"] = meta.get("/ModDate")
        paginas_texto = [p.extract_text() or "" for p in lector.pages[:3]]
        texto = "\n".join(paginas_texto)
        # Líneas tal cual (sin normalizar) de la 1.ª página: para extraer campos de formato fijo.
        info["lineas_texto"] = [l.strip() for l in (paginas_texto[0] if paginas_texto else "").splitlines() if l.strip()]
        info["texto"] = normalizar(texto)
        info["caracteres_texto"] = len(info["texto"])
        info["imagenes_embebidas"] = sum(len(p.images) for p in lector.pages[:3])

        tiene_texto = info["caracteres_texto"] >= MIN_CHARS_TEXTO
        fondo_limpio = blanco is None or blanco >= UMBRAL_BLANCO_PURO
        info["digital_pdf"] = tiene_texto and fondo_limpio
        if not tiene_texto:
            info["motivo_no_digital"] = "El PDF no tiene texto: es una imagen o un escaneo."
        elif not fondo_limpio:
            info["motivo_no_digital"] = "El PDF tiene texto pero el fondo no es blanco puro como en un documento digital (posible escaneo con OCR)."
    else:
        info["digital_pdf"] = None  # una imagen suelta nunca es el documento digital original
    return info
