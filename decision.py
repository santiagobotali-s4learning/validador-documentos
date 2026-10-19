"""Combina las señales (archivo, Gemini, reglas) en un resultado: aceptado / revisar / rechazado.

Función pura: no llama a ningún servicio, por eso se puede probar sin Gemini.
"""
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlparse

import reglas_curp
from captura import MIN_CHARS_TEXTO, normalizar
from composicion import otros_documentos as composicion_otros
from config_documentos import DOCUMENTOS, MAX_IMPORTANTES_FALTANTES


def _tiene_texto(info: dict) -> bool:
    """¿El PDF trae capa de texto? Alcanza para leer leyendas, sin exigir que sea 'digital original'."""
    return info["formato"] == "pdf" and info["caracteres_texto"] >= MIN_CHARS_TEXTO


def _check_final(check_id: str, cfg: dict, gem: dict, info: dict) -> dict:
    """Resuelve un check. Prioridad: código (QR) > texto del PDF digital (solo si lo encuentra) > Gemini."""
    g = gem["checks"][check_id]
    resultado = {"nivel": cfg["nivel"], "presente": g["presente"], "fuente": "gemini", "evidencia": g["evidencia"]}

    if check_id == "codigo_qr" and (info["qr"] or info["qr_detectados"]):
        leido = bool(info["qr"])
        resultado.update(
            presente=True, fuente="codigo",
            evidencia="QR decodificado" if leido else "QR detectado pero no legible",
        )
    elif check_id == "codigo_barras" and info["codigo_barras"]:
        resultado.update(presente=True, fuente="codigo", evidencia="Código de barras detectado")
    elif _tiene_texto(info) and cfg.get("patrones"):
        # El texto hallado prueba que está; el no hallado no prueba que falte (puede ser parte de
        # una imagen, como el encabezado de la CURP): en ese caso decide Gemini.
        hallado = next((p for p in cfg["patrones"] if normalizar(p) in info["texto"]), None)
        if hallado:
            resultado.update(presente=True, fuente="texto_pdf", evidencia=hallado)
    return resultado


_CURP_EN_TEXTO = re.compile(r"[A-Z][AEIOUX][A-Z]{2}\d{6}[HMX][A-Z]{2}[B-DF-HJ-NP-TV-Z]{3}[0-9A-Z]\d")


def _detalle_qr(cfg: dict, qr: list[str]) -> list[dict]:
    """Contenido de cada QR leído, desarmado para consultarlo: si es un enlace, su dominio, si el
    dominio está en la lista oficial del tipo (cuando la hay) y los parámetros de la URL."""
    detalle = []
    for texto in qr:
        item = {"contenido": texto, "es_url": False}
        datos = reglas_curp.datos_qr_curp(texto)
        if datos:
            item["datos"] = datos
        if texto.lower().startswith(("http://", "https://")):
            url = urlparse(texto)
            item |= {
                "es_url": True,
                "dominio": url.hostname,
                "ruta": url.path,
                "parametros": dict(parse_qsl(url.query)),
            }
            if cfg.get("qr_dominios"):
                item["dominio_oficial"] = url.hostname in cfg["qr_dominios"]
        detalle.append(item)
    return detalle


def _cruzar_qr_curp(qr: list[str], campos: dict, curp_valida: str | None) -> list[str]:
    """Constancia de CURP: lo que dice el QR tiene que coincidir con lo que muestra el documento y
    con lo que codifica la propia clave (sexo, fecha y entidad de nacimiento)."""
    for texto in qr:
        datos = reglas_curp.datos_qr_curp(texto)
        if datos:
            break
    else:
        return []
    avisos = []
    # Nombre: mismas palabras, sin importar el orden (el QR separa apellidos y nombre).
    del_qr = reglas_curp.palabras_nombre(
        " ".join(filter(None, [datos["nombre"], datos["apellido_paterno"], datos["apellido_materno"]]))
    )
    del_doc = reglas_curp.palabras_nombre(campos.get("nombre"))
    if del_doc and del_qr != del_doc:
        avisos.append(f"El nombre del QR ({' '.join(filter(None, [datos['nombre'], datos['apellido_paterno'], datos['apellido_materno']]))}) no coincide con el del documento ({campos.get('nombre')}).")
    # Sexo, fecha y entidad de nacimiento del QR contra la clave (la leída y válida).
    clave = reglas_curp.limpiar(curp_valida)
    if len(clave) == 18 and reglas_curp.PATRON.match(clave):
        sexo_clave = {"H": "HOMBRE", "M": "MUJER"}.get(clave[10])
        if sexo_clave and datos["sexo"] and reglas_curp._sin_acentos(datos["sexo"]) != sexo_clave:
            avisos.append(f"El sexo del QR ({datos['sexo']}) no coincide con el de la CURP ({sexo_clave}).")
        nacimiento = reglas_curp.fecha_nacimiento(clave)
        if nacimiento and datos["fecha_nacimiento"] and datos["fecha_nacimiento"] != nacimiento.strftime("%d/%m/%Y"):
            avisos.append(f"La fecha de nacimiento del QR ({datos['fecha_nacimiento']}) no coincide con la de la CURP ({nacimiento.strftime('%d/%m/%Y')}).")
        abrev_qr = reglas_curp.entidad_a_abreviatura(datos["entidad_nacimiento"])
        if abrev_qr and abrev_qr != clave[11:13]:
            avisos.append(f"La entidad de nacimiento del QR ({datos['entidad_nacimiento']}) no coincide con la de la CURP ({reglas_curp.ENTIDADES.get(clave[11:13])}).")
    # Entidad de registro: el QR trae su código numérico; el documento, el nombre.
    abrev_codigo = reglas_curp.CODIGO_ENTIDAD.get(datos["codigo_entidad_registro"] or "")
    abrev_doc = reglas_curp.entidad_a_abreviatura(campos.get("entidad_registro"))
    if abrev_codigo and abrev_doc and abrev_codigo != abrev_doc:
        avisos.append(f"La entidad de registro del QR (código {datos['codigo_entidad_registro']}) no coincide con la del documento ({campos.get('entidad_registro')}).")
    return avisos


def _revisar_qr(cfg: dict, qr: list[str], curp_leida: str | None) -> list[str]:
    """Observaciones sobre el contenido del QR ya decodificado (todas llevan a 'revisar')."""
    avisos = []
    dominios = cfg.get("qr_dominios")
    if dominios:
        hosts = [urlparse(t).hostname for t in qr if t.lower().startswith(("http://", "https://"))]
        if not hosts:
            avisos.append("El QR no contiene un enlace de verificación.")
        else:
            extra = sorted({h for h in hosts if h not in dominios})
            if extra:
                avisos.append(f"El QR apunta a un dominio no reconocido como oficial: {', '.join(extra)}.")
    # Si el QR trae una CURP (la constancia de CURP siempre; algunos certificados, en la URL),
    # tiene que ser la que se lee en el documento.
    curp_qr = {m for t in qr for m in _CURP_EN_TEXTO.findall(t.upper())}
    leida = reglas_curp.limpiar(curp_leida)
    if curp_qr and leida and leida not in curp_qr:
        avisos.append(f"La CURP del QR ({', '.join(sorted(curp_qr))}) no coincide con la del documento ({leida}).")
    return avisos


def _variante_final(gem_variante: str | None, checks: dict) -> str | None:
    """La variante del certificado se decide por lo que se ve, no por la etiqueta suelta del modelo:
    solo firma manuscrita -> semielectrónico; solo sello/firma electrónica -> electrónico. Si hay
    ambas o ninguna, no hay base para corregirla y se mantiene la del modelo."""
    firma = checks.get("firma_autografa", {}).get("presente")
    electronico = checks.get("sello_o_firma_electronica", {}).get("presente")
    if firma is None or electronico is None:
        return gem_variante
    if electronico and not firma:
        return "electronico"
    if firma and not electronico:
        return "semielectronico"
    return gem_variante


def _revisar_variante(cfg: dict, variante: str | None, checks: dict) -> list[str]:
    reglas = cfg.get("reglas_variante", {}).get(variante)
    if not reglas:
        return []
    avisos = []
    for cid in reglas["esperados"]:
        if cid in checks and not checks[cid]["presente"]:
            avisos.append(f"No se detectó «{cfg['checks'][cid]['descripcion']}», propio del certificado {variante}.")
    for cid in reglas["no_esperados"]:
        if cid in checks and checks[cid]["presente"]:
            avisos.append(f"Se detectó «{cfg['checks'][cid]['descripcion']}», que no corresponde a un certificado {variante}.")
    return avisos


_HOST_SIN_ESQUEMA = re.compile(r"^(?:[\w-]+\.)+[a-z]{2,}(?:[/:?#]|$)", re.I)


def _url_impresa(impreso: str | None) -> str | None:
    """Enlace impreso en el documento como URL usable. Suele venir sin 'http://' (www.sitio.gob.mx/...)."""
    impreso = (impreso or "").strip()
    if impreso.lower().startswith(("http://", "https://")):
        return impreso
    if _HOST_SIN_ESQUEMA.match(impreso):
        return "http://" + impreso
    return None


def _revisar_enlace_impreso(qr: list[str], impreso: str | None) -> list[str]:
    """El enlace impreso en el documento y el del QR deberían apuntar al mismo sitio."""
    impreso = _url_impresa(impreso)
    if not impreso:
        return []
    hosts_qr = {urlparse(t).hostname for t in qr if t.lower().startswith(("http://", "https://"))}
    host = urlparse(impreso).hostname
    if hosts_qr and host not in hosts_qr:
        return [f"El enlace impreso ({host}) no coincide con el dominio del QR ({', '.join(sorted(h for h in hosts_qr if h))})."]
    return []


def _revisar_origen(cfg: dict, info: dict) -> list[str]:
    """Señales de que el PDF no es el archivo original del sistema emisor (todas llevan a 'revisar')."""
    avisos = []
    umbral = cfg.get("umbral_blanco_puro")
    if umbral is not None and info["blanco_puro"] is not None and info["blanco_puro"] < umbral:
        avisos.append(
            f"La página tiene {info['blanco_puro']:.0%} de fondo en blanco exacto y una constancia original más de "
            f"{umbral:.0%}: podría ser una reimpresión, una captura o un escaneo con texto reconocido."
        )
    huella = cfg.get("huella_origen")
    if huella:
        productor, creador = info.get("productor") or "", info.get("creador") or ""
        if not productor.startswith(huella["productor"]) or not creador.startswith(huella["creador"]):
            avisos.append(
                f"El PDF no fue generado por el sistema emisor: productor '{productor or 'vacío'}' y creador "
                f"'{creador or 'vacío'}' (se esperaba {huella['productor']} / {huella['creador']})."
            )
        creado, modificado = info.get("fecha_creacion"), info.get("fecha_modificacion")
        if huella.get("sin_modificaciones") and creado and modificado and creado != modificado:
            avisos.append(f"El PDF fue modificado después de generarse (creado {creado}, modificado {modificado}).")
    return avisos


SIMILITUD_MINIMA_TEXTO = 0.93


def _mismo_valor(campo: str, a: str, b: str) -> bool:
    if campo in ("clave", "curp"):
        a, b = reglas_curp.limpiar(a), reglas_curp.limpiar(b)
        # O/I leídas en lugar de 0/1 no cuentan como diferencia (ver reglas_curp.validar)
        return a == b or (len(a) == 18 and reglas_curp._corregir_lectura(a) == b)
    if campo.startswith("entidad"):
        abrev_a, abrev_b = reglas_curp.entidad_a_abreviatura(a), reglas_curp.entidad_a_abreviatura(b)
        if abrev_a and abrev_b:
            return abrev_a == abrev_b
    palabras_a, palabras_b = reglas_curp.palabras_nombre(a), reglas_curp.palabras_nombre(b)
    if palabras_a == palabras_b:
        return True
    # Texto libre (nombre, entidad): se tolera un error de lectura de una o dos letras (caso real:
    # 'MICHOACAN DE OCAMPI' leído por la IA contra 'MICHOACAN DE OCAMPO' del PDF). Un cambio de nombre o
    # de apellido deja la similitud muy por debajo.
    similitud = SequenceMatcher(None, " ".join(sorted(palabras_a)), " ".join(sorted(palabras_b))).ratio()
    return similitud >= SIMILITUD_MINIMA_TEXTO


def _campos_finales(cfg: dict, info: dict, del_modelo: dict, revisiones: list[str]) -> tuple[dict, dict]:
    """Campos de la respuesta y de qué fuente sale cada uno ('texto_pdf' o 'gemini').

    Si el documento admite extracción por texto (`campos_desde_texto`) y el PDF la trae, esos valores
    mandan: son exactos (la IA puede leer mal un carácter). Si lo que ve Gemini no coincide con el
    texto, se revisa: puede ser un error de lectura, o una imagen superpuesta al texto original.
    """
    campos = dict(del_modelo)
    fuentes = {k: "gemini" for k in campos}
    if not cfg.get("campos_desde_texto") or info["formato"] != "pdf":
        return campos, fuentes
    del_texto = reglas_curp.datos_texto_constancia(info.get("lineas_texto") or [])
    for campo, valor in (del_texto or {}).items():
        visto = del_modelo.get(campo)
        if visto and not _mismo_valor(campo, valor, visto):
            revisiones.append(
                f"Lo que se ve en el documento ({campo}: '{visto}') no coincide con el texto del PDF ('{valor}'): "
                "puede ser un error de lectura o una imagen superpuesta al texto original."
            )
        campos[campo] = valor
        fuentes[campo] = "texto_pdf"
    return campos, fuentes


def evaluar(
    tipo: str, info: dict, gem: dict, aceptar_imagenes: bool = False, composicion: list[dict] | None = None
) -> dict:
    """composicion: qué documento hay en cada página de un PDF de varias páginas (composicion.combinar).
    info y gem corresponden solo a las páginas del documento pedido."""
    cfg = DOCUMENTOS[tipo]
    rechazos: list[str] = []
    revisiones: list[str] = []

    # 0) ¿El archivo trae solo el documento pedido? (PDF de varias páginas)
    if composicion:
        otros = composicion_otros(composicion, tipo)
        if otros:
            rechazos.append(
                f"El archivo trae otros documentos junto con {cfg['articulo']} {cfg['nombre_corto']}: "
                f"{', '.join(otros)}. Subí un archivo que contenga solo {cfg['articulo']} {cfg['nombre_corto']}."
            )

    # 1) ¿Es el tipo de documento esperado?
    if gem["tipo_detectado"] != tipo:
        rechazos.append(
            f"El documento no parece ser: {cfg['nombre']} (se detectó: {gem['tipo_detectado']})."
        )

    # 2) ¿Es digital y no un escaneo/foto?
    if cfg["requiere_pdf_digital"]:
        if info["formato"] == "imagen":
            msg = "Se subió una imagen. Subí el PDF original descargado del portal oficial, sin imprimir ni escanear."
            (revisiones if aceptar_imagenes else rechazos).append(msg)
        elif not info["digital_pdf"]:
            rechazos.append(info["motivo_no_digital"] + " Subí el PDF original, sin imprimir ni escanear.")
        elif gem.get("captura") in ("escaneo", "foto"):
            revisiones.append(f"El PDF parece un {gem['captura']} según el análisis visual.")

    # 3) Elementos esperados del formato
    checks = {cid: _check_final(cid, ccfg, gem, info) for cid, ccfg in cfg["checks"].items()}
    faltan_importantes = []
    for cid, c in checks.items():
        if c["presente"]:
            continue
        desc = cfg["checks"][cid]["descripcion"]
        # Checks redactados en positivo ("está libre de X"): su ausencia se explica con un mensaje
        # propio, porque "falta: está libre de X" se lee al revés de lo que significa.
        propio = cfg["checks"][cid].get("mensaje_si_falta")
        if propio:
            evidencia = f" ({c['evidencia']})" if c.get("evidencia") else ""
            (rechazos if c["nivel"] == "critico" else revisiones).append(f"{propio}{evidencia}.")
        elif c["nivel"] == "critico":
            rechazos.append(f"Falta un elemento obligatorio: {desc}.")
        elif c["nivel"] == "importante":
            faltan_importantes.append(f"No se detectó: {desc}.")
    # Una sola ausencia puede ser una mala captura (revisar); varias juntas indican otro formato.
    if len(faltan_importantes) > MAX_IMPORTANTES_FALTANTES:
        rechazos.append("Faltan varios elementos propios del formato oficial.")
    revisiones.extend(faltan_importantes)

    if "codigo_qr" in checks and checks["codigo_qr"]["presente"] and not info["qr"]:
        revisiones.append("Se ve un código QR pero no se pudo leer. Revisá la calidad del archivo.")

    # 3d) Campos: en un PDF digital con formato conocido, se toman de la capa de texto (exactos);
    # lo que leyó Gemini queda como segunda lectura y se compara.
    campos, fuentes = _campos_finales(cfg, info, gem["campos"], revisiones)

    # 4) Campo clave y sus reglas
    clave_id = cfg["campo_clave"]
    valor = campos.get(clave_id)
    validacion = None
    if clave_id in ("clave", "curp"):
        if valor:
            validacion = reglas_curp.validar(valor)
            if not validacion["valida"]:
                revisiones.append("La CURP leída no cumple las reglas: " + "; ".join(validacion["errores"]) + ".")
            elif _tiene_texto(info) and reglas_curp.limpiar(valor) not in info["texto"].replace(" ", ""):
                revisiones.append("La CURP leída por el modelo no aparece en el texto del PDF.")
        elif tipo == "curp":
            rechazos.append("No se pudo leer la clave CURP.")
        else:
            revisiones.append("El documento no muestra una CURP legible para cruzar datos.")

    # 3b) Estructura del PDF: imágenes de más respecto al formato oficial (marca de agua, edición)
    tope = cfg.get("max_imagenes_embebidas")
    if tope is not None and info["formato"] == "pdf" and info.get("imagenes_embebidas", 0) > tope:
        revisiones.append(
            f"El archivo PDF contiene {info['imagenes_embebidas']} imágenes internas y la constancia oficial "
            f"{tope} (encabezado, 2 códigos QR y código de barras): la imagen de más suele ser una marca de "
            "agua agregada por otra aplicación o una edición del archivo."
        )

    # 3c) Origen del PDF (solo PDF con texto: los escaneos ya se rechazan por no tenerlo)
    if info["formato"] == "pdf" and _tiene_texto(info):
        revisiones.extend(_revisar_origen(cfg, info))

    # 4b) Contenido del QR (si se pudo leer) y variante del certificado
    revisiones.extend(_revisar_qr(cfg, info["qr"], valor))
    if tipo == "curp":
        valida = (validacion or {}).get("curp_corregida") or valor
        revisiones.extend(_cruzar_qr_curp(info["qr"], campos, valida))
    variante = _variante_final(gem.get("variante"), checks)
    if "variantes" in cfg:
        if variante == "no_reconocido":
            revisiones.append("No se pudo identificar como certificado electrónico ni semielectrónico.")
        revisiones.extend(_revisar_variante(cfg, variante, checks))
        revisiones.extend(_revisar_enlace_impreso(info["qr"], gem["campos"].get("enlace_verificacion_impreso")))

    # 5) Criterios aún no validados con ejemplos reales
    if cfg.get("provisorio") and not rechazos:
        revisiones.append("Criterios de este documento aún provisorios: se requiere revisión manual.")

    # El análisis de origen digital (blanco puro, captura según Gemini) solo aplica a los documentos
    # que exigen PDF digital original (CURP); en el resto no se informa para no confundir.
    captura_info = {"formato": info["formato"], "paginas": info["paginas"], "caracteres_texto": info["caracteres_texto"]}
    if cfg["requiere_pdf_digital"]:
        captura_info |= {
            "digital_pdf": info["digital_pdf"],
            "blanco_puro": info["blanco_puro"],
            "productor": info["productor"],
            "creador": info.get("creador"),
            "fecha_creacion": info.get("fecha_creacion"),
            "fecha_modificacion": info.get("fecha_modificacion"),
            "segun_gemini": gem.get("captura"),
        }

    resultado = "rechazado" if rechazos else "revisar" if revisiones else "aceptado"
    return {
        "tipo": tipo,
        "variante": variante,
        "composicion": composicion,
        "paginas_analizadas": [p["pagina"] for p in composicion if p["documento"] == tipo] if composicion else None,
        "variante_segun_modelo": gem.get("variante"),
        "resultado": resultado,
        "motivos": rechazos + revisiones,
        "campo_clave": {"campo": clave_id, "valor": valor, "validacion": validacion},
        "campos": campos,
        "campos_fuente": fuentes,
        "campos_segun_modelo": gem["campos"],
        "checks": checks,
        "captura": captura_info,
        "qr": {
            "detectados": info["qr_detectados"],
            "leidos": info["qr"],
            "detalle": _detalle_qr(cfg, info["qr"]),
            "enlace_impreso": _url_impresa(gem["campos"].get("enlace_verificacion_impreso")),
        },
    }
