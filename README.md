# Validación de formato de documentos (solo Gemini)

Primera instancia de carga: decide si el documento tiene el **formato** esperado
(`aceptado` / `revisar` / `rechazado`). La autenticidad se verifica después con APIs oficiales.

Documentos: `curp` (constancia digital) y `certificado_bachillerato` (**criterios provisorios**).

## Pipeline (`POST /validar`, campos: `file`, `tipo` opcional)
1. `captura.py` — código: ¿PDF digital o escaneo/foto? texto del PDF, QR, código de barras.
2. `motor_gemini.py` — Gemini: tipo, checklist visual con evidencia, campos.
3. `decision.py` — combina todo. Prioridad por check: código (QR/barras) > texto del PDF > Gemini.
4. `reglas_curp.py` — estructura y dígito verificador de la CURP.

Qué exige cada formato: `config_documentos.py` (niveles critico / importante / opcional).

## Foto del certificado con el celular (`movil.py`)
Solo para el certificado (la CURP exige el PDF digital). La computadora crea una sesión (`POST /movil/sesiones`)
y muestra un QR a `/movil/{id}`; el celular saca una foto por hoja y las sube; se juntan en un PDF (una página
por foto) que la computadora baja una sola vez y manda a `/validar` como un archivo local. La sesión vence a los 15 min.
Las sesiones se guardan en el bucket `MOVIL_BUCKET` (en Cloud Run, compartido entre instancias) o, sin esa
variable, en una carpeta temporal local. El celular pasa por IAP: hay que iniciar sesión con una cuenta autorizada.

## Correr en local
    $env:GCP_PROJECT="validador-documentos-api"      # o GEMINI_API_KEY
    .\.venv\Scripts\uvicorn validar:app --port 8080  # docs en /docs
    .\.venv\Scripts\python -m pytest tests           # sin llamar a Gemini

`ACEPTAR_IMAGENES=1` solo para pruebas: una imagen pasa a `revisar` en lugar de `rechazado`.

## Document AI
`motor_documentai.py` está preparado (mismo contrato que `motor_gemini.py`) pero sin implementar.
