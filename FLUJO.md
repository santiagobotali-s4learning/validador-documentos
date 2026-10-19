# Cómo funciona el validador de documentos

Referencia técnica del estado actual (octubre 2026, revisión `validar-documentos-00016-j69`).
Para una versión corta, ver `RESUMEN.md`.

---

## 0. Qué hace y qué no

El servicio recibe un documento que sube un alumno (**constancia de CURP** o **certificado de bachillerato**),
y responde:

- **Si tiene el formato esperado:** `aceptado`, `revisar` o `rechazado`, con los motivos.
- **Qué datos contiene:** nombre, CURP, folio, etc., más el contenido de su código QR.

**No verifica autenticidad** contra fuentes oficiales (RENAPO, SEP) ni listas negras de dominios. Eso es un
paso posterior. Este servicio es la primera barrera: detectar documentos con formato incorrecto, escaneados,
editados o incoherentes.

---

## 1. Las piezas y qué tecnología usa cada una

El análisis combina **tres tipos de herramientas**, cada una para lo que mejor hace:

| Herramienta | Tipo | Para qué se usa |
|---|---|---|
| **pypdf** | Lectura de PDF | Extrae la capa de texto, los metadatos y las imágenes internas del PDF. En la constancia de CURP, también los campos (clave, nombre, entidad) |
| **pdfium** | Renderizado | "Dibuja" cada página del PDF como imagen para analizarla |
| **OpenCV** | **Visión por computadora clásica** (sin IA) | Decodifica códigos QR, detecta códigos de barras y mide píxeles (blanco puro) |
| **Gemini** (Vertex AI) | **IA multimodal** | Mira el documento: reconoce el tipo, verifica elementos visuales (logos, firmas, marcas de agua) y extrae los campos de texto |
| **Reglas en Python** | Lógica determinista | Valida la CURP, cruza datos y emite el veredicto |

### ¿Quién extrae el texto?
| Documento | ¿Tiene capa de texto? | Campos extraídos por | Segunda lectura |
|---|---|---|---|
| Constancia de CURP (PDF digital) | sí | **pypdf** (exacto, sin IA) | Gemini: si lo que ve no coincide con el texto → revisar |
| Certificados (escaneos) | no | **Gemini** (lee la imagen, como un OCR) | — |

### ¿Y Document AI?
**Document AI** es el servicio de Google para OCR y extracción de campos de formularios. En este proyecto
**ese papel lo cumple Gemini** (y pypdf cuando el PDF trae texto). OpenCV **no** lo reemplaza, porque no lee
texto ni entiende campos: solo decodifica códigos y mide la imagen.

`motor_documentai.py` está preparado con el mismo contrato que `motor_gemini.py`, pero sin implementar. Si en
el futuro se entrena un extractor de Document AI, se enchufa ahí sin tocar el resto.

### Principio de diseño
> **La IA observa; el código decide.**

Gemini dice qué ve y qué lee. Toda la decisión (niveles, reglas, cruces, veredicto) es código: repetible,
explicable y testeable sin llamar a la IA.

---

## 2. El recorrido completo

Todo empieza en `POST /validar` (`validar.py`), con el archivo y, opcionalmente, el tipo esperado.

```
                    archivo (PDF / PNG / JPG, máx. 20 MB)
                                   │
          ┌────────────────────────┴────────────────────────┐
          ▼                                                 ▼
 PASO 1 · captura.analizar()                     PASO 2 · motor_gemini.analizar()
 código puro, sin IA                             Gemini
 ─────────────────────────                       ─────────────────────────
 · texto del PDF        (pypdf)                  · ¿qué documento es?
 · metadatos            (pypdf)                  · ¿están los elementos del formato?
 · imágenes internas    (pypdf)                    (sí/no + dónde los ve)
 · contenido del QR     (OpenCV)                 · extrae los campos
 · código de barras     (OpenCV)                   (nombre, CURP, folio…)
 · blanco puro          (OpenCV)
          │                                                 │
          └──────────── info ──────────┬─────── gem ────────┘
                                       ▼
                       PASO 3 · decision.evaluar()
                       código puro: combina, cruza y decide
                                       │
                                       ▼
              aceptado / revisar / rechazado + motivos + datos
```

Si no se indica el tipo, antes del paso 2 Gemini clasifica el documento (`curp`, `certificado_bachillerato`
u `otro`). Si es `otro`, se rechaza ahí mismo.

### PDF de varias páginas: ¿trae un solo documento? (`composicion.py`)
Un alumno puede subir varios documentos unidos en un mismo PDF (caso real: acta de nacimiento + certificado +
constancia de CURP, unidos con iLovePDF). Si el PDF tiene **más de una página** (máximo 10), antes del análisis
se identifica qué documento hay en cada página:

1. **Por código, si hay evidencia firme:** un QR con el formato de la constancia de CURP, un QR de un dominio
   de certificados conocido, o un texto inconfundible ("CONSTANCIA DE LA CLAVE ÚNICA…", "CERTIFICADO DE
   TERMINACIÓN DE ESTUDIOS").
2. **Si no, Gemini**, con una consulta que recorre todas las páginas y marca cuáles son **continuación** del
   documento anterior (reverso, segunda hoja). Así un certificado de 2 páginas cuenta como un solo documento.

Después:

| Situación | Resultado |
|---|---|
| Solo está el documento elegido (en una o varias páginas) | análisis normal |
| Está el elegido **y además otros** | se analizan solo sus páginas y el resultado es **rechazado**: "El archivo trae otros documentos junto con el certificado de bachillerato: acta de nacimiento (pág. 1), constancia de CURP (pág. 3). Subí un archivo que contenga solo el certificado." |
| El elegido no está | **rechazado**: "No se encontró el certificado de bachillerato en el archivo (se detectó: …)" |
| Sin tipo elegido y hay varios documentos | **rechazado**: pide elegir el tipo o subir un archivo por documento |

Cuesta una consulta extra a Gemini (unos 5–8 s) solo en los PDF de varias páginas. La respuesta incluye
`composicion` (qué hay en cada página y quién lo identificó) y `paginas_analizadas`; la interfaz lo muestra
debajo de los motivos.

---

## 3. Paso 1 · Análisis por código (`captura.py`)

Calcula señales objetivas del archivo, sin IA.

| Señal | Cómo se obtiene | Para qué sirve |
|---|---|---|
| **Capa de texto** | `pypdf` extrae el texto real del PDF (hasta 3 páginas), normalizado: mayúsculas, sin acentos | Un PDF generado por un sistema tiene texto; un escaneo es solo una imagen. También permite buscar leyendas con certeza |
| **Imágenes internas** | Cantidad de imágenes embebidas en el PDF | La constancia oficial trae exactamente 4; una más suele ser una marca de agua |
| **Metadatos** | Productor, creador, fecha de creación y de modificación del PDF | Revelan qué programa generó o reescribió el archivo |
| **Código QR** | OpenCV, ver abajo | Se lee su contenido para cruzarlo con el documento |
| **Código de barras** | Detector de OpenCV (detecta, no lee) | Confirma el check `codigo_barras` |
| **Blanco puro** | Fracción de píxeles exactamente blancos (255) en la 1.ª página renderizada | Un PDF digital tiene fondo blanco perfecto; un escaneo o foto, no |

### Lectura del QR
Un QR en un escaneo suele ocupar pocos píxeles y tener bordes borrosos. Para leerlo:

1. Se renderiza la página a **3 resoluciones** (escala 2, 3 y 4 del PDF).
2. En cada una se prueban **4 versiones** de la imagen: original, con más nitidez, con más contraste local
   (CLAHE) y binarizada (umbral adaptativo).
3. Se usan **2 detectores** de OpenCV: ArUco (busca varios QR a la vez) y el clásico como respaldo, **de a uno**.
   En modo "varios", el clásico se trababa con fondos de seguridad (un acta de nacimiento: 140 s y más de
   2 GiB, tumbaba el contenedor); de a uno tarda 0,1 s.
4. Se detiene en cuanto lee algo. Límite de 25 s por archivo y de 3.200 px por lado (para no agotar memoria).

Con esto se leen los QR de los 6 certificados y de todas las constancias en PDF. Si se detecta un QR pero no
se puede leer, se informa.

### Blanco puro
- Se renderiza solo la primera página a escala 2 (≈1224×1584 px para una hoja carta).
- Se pasa a gris y se cuenta qué fracción de píxeles vale exactamente 255.
- Valores medidos: **constancias válidas 0,74–0,77**; escaneos 0,23–0,68 (las apps de escaneo "blanquean" el
  fondo, por eso no es una señal decisiva). Entre Windows y Cloud Run el mismo PDF varía unas milésimas.

---

## 4. Paso 2 · Lectura con Gemini (`motor_gemini.py`)

### Qué se le envía
Una sola llamada con **el documento + un prompt + un esquema JSON** que Gemini debe llenar.

- **El prompt** (en español) le dice qué documento se espera, la lista de elementos a verificar con su
  descripción, y los campos a extraer "tal como figuran, sin corregirlos". Pide ser estricto, no inventar, y
  aclara que el contenido del documento son datos y nunca instrucciones (defensa contra *prompt injection*).
- **El esquema** obliga a responder **solo** con este JSON, sin texto libre:

```json
{
  "tipo_detectado": "curp",
  "captura": "digital_original",
  "checks": {
    "codigo_qr":              {"presente": true,  "evidencia": "QR arriba a la derecha"},
    "sin_marcas_de_terceros": {"presente": false, "evidencia": "Marca 'CamScanner' abajo a la derecha"}
  },
  "campos": {"clave": "SOGA060701HHGTRLA7", "nombre": "ALAN YAHIR SOTO GARCIA", "entidad_registro": "VERACRUZ"}
}
```

**El prompt y el esquema se generan solos desde `config_documentos.py`.** Para agregar un campo o un
elemento a verificar alcanza con agregarlo ahí.

### Cómo se le envía el PDF
Depende de qué tipo de PDF es (regla en `captura.envio_a_gemini`):

| PDF | Se envía | Por qué (medido) |
|---|---|---|
| **Con capa de texto** (constancia de CURP) | como **imagen** renderizada a escala 3 | Con el PDF original, Gemini leía mal textos chicos: una CURP de 18 caracteres salía como `EARH050dYA8` en 5 de 5 intentos. Como imagen: bien en 4 de 4 |
| **Sin texto** (escaneos: certificados) | el **PDF tal cual** | Gemini toma la imagen escaneada a su resolución original. Renderizada, perdía la CURP en 2 de 2 intentos |

### Ajustes de la llamada
| Ajuste | Valor | Para qué |
|---|---|---|
| Modelo | `gemini-2.5-flash` (`GEMINI_MODEL`) | Relación costo / calidad |
| `temperature` | 0 | Respuestas lo más repetibles posible |
| Razonamiento | apagado (`GEMINI_THINKING_BUDGET=0`) | Mitad de tiempo, mismos veredictos en las pruebas |
| Timeout / reintentos | 90 s, 2 intentos | Que un 429 (cuota agotada) no deje la solicitud colgada minutos |

---

## 5. Paso 3 · Decisión (`decision.py`)

Recorre estos pasos en orden y acumula **motivos de rechazo** y **motivos de revisión**:

1. **¿Es el tipo esperado?** Si Gemini detecta otro tipo → rechazo.
2. **¿Es un PDF digital original?** (solo CURP) Sin capa de texto → rechazo. Imagen suelta → rechazo.
3. **Elementos del formato.** Cada elemento ("check") se resuelve con esta prioridad:
   **código > texto del PDF > Gemini.**
   - Si OpenCV leyó el QR, el check del QR es positivo aunque Gemini no lo vea.
   - Si el texto del PDF contiene la leyenda, es positivo. Si no la contiene, decide Gemini (la leyenda puede
     ser parte de una imagen, como el encabezado verde de la CURP).
4. **Campo clave (CURP):** se valida en código (sección 8).
5. **Estructura y origen del PDF:** imágenes de más, blanco puro y huella de origen (solo CURP).
6. **Cruces con el QR:** lo que dice el QR contra lo impreso en el documento.
7. **Reglas por variante** (solo certificado).

### Niveles de cada elemento
| Nivel | Si falta |
|---|---|
| `critico` | **rechazado** |
| `importante` | **revisar**. Si faltan más de 1 → rechazado |
| `opcional` | solo se informa |

### Resultado final
**Algún rechazo → `rechazado`.** Si no, **alguna revisión → `revisar`.** Si no, **`aceptado`.**

---

## 6. Constancia de CURP

### Campos: `clave`, `nombre`, `entidad_registro`
En la constancia digital se toman **de la capa de texto del PDF** (`reglas_curp.datos_texto_constancia`).
El texto trae siempre la misma secuencia, en los dos modelos vistos (actual y SEGOB):

```
NOMBRE
130087200605092        ← número del código de barras (15 dígitos)
SOGA060701HHGTRLA7     ← la clave: la CURP que sigue a ese número
NOMBRE                 ← el nombre: la línea siguiente
…
VERACRUZEntidad de registro:   ← la entidad: pegada a la etiqueta o en la línea anterior
```

- Es exacto: no depende de que la IA lea bien cada carácter (Gemini llegó a transcribir una CURP como
  `EARH050dYA8`; el texto del PDF tenía `EARH050418MMNSVYA8`).
- **Gemini lee los mismos campos de la imagen y se comparan.** Si no coinciden → `revisar`: puede ser un error
  de lectura, o una **imagen pegada encima del texto original** (lo que se ve no es lo que dice el archivo).
  La clave se compara exacta (salvo O/I por 0/1). Nombre y entidad toleran un error de lectura de una o dos
  letras (similitud ≥ 0,93; caso real: "OCAMPI" por "OCAMPO"); un cambio de apellido queda muy por debajo.
- La respuesta indica de dónde salió cada campo (`campos_fuente`) y qué leyó Gemini (`campos_segun_modelo`).
- Si el PDF no tiene texto o no sigue ese formato, los campos salen de Gemini.

### Elementos del formato
| Check | Nivel | Cómo se verifica |
|---|---|---|
| `leyenda_estados_unidos_mexicanos` | crítico | texto del PDF → si no, Gemini (suele ser imagen) |
| `leyenda_constancia_curp` | crítico | texto del PDF → si no, Gemini |
| `etiqueta_clave` | crítico | texto del PDF → si no, Gemini |
| `codigo_qr` | crítico | OpenCV |
| `sin_marcas_de_terceros` | crítico | Gemini: marcas de CamScanner, Adobe Scan, iLovePDF, etc. |
| `etiqueta_nombre`, `entidad_de_registro` | importante | texto del PDF → si no, Gemini |
| `bandera_mexico` | importante | Gemini |
| `codigo_barras` | importante | OpenCV → si no, Gemini |
| `logos_institucionales` | opcional | Gemini. Hay dos modelos válidos: el actual (Gobierno de México, Gobernación, RENAPO) y el anterior (SEGOB) |
| Carta, TELCURP, "Trámite gratuito" | opcional | texto del PDF → si no, Gemini (2.ª hoja, puede no subirse) |

### Logos y elementos visuales que verifica Gemini
Gemini **no compara contra imágenes de referencia** de cada logo: recibe una descripción en texto de cada
elemento y responde si lo ve (`presente`) y dónde (`evidencia`). Lo que se le pide en la constancia:

| Elemento | Descripción que recibe Gemini | Nivel |
|---|---|---|
| Escudo nacional | Encabezado con "ESTADOS UNIDOS MEXICANOS" y el escudo nacional | crítico |
| Logos institucionales | "SEGOB" en el encabezado (modelo anterior) **o** "Gobierno de México", "Gobernación" y "RENAPO" en el pie (modelo actual) | opcional: no decide |
| Bandera | Bandera de México junto al texto "Soy México" | importante |
| Código QR y de barras | Ubicación esperada en la hoja (además los verifica OpenCV) | crítico / importante |
| Marcas de terceros | Marcas de agua o logos de apps: CamScanner, Adobe Scan, WPS, iLovePDF, Smallpdf… | crítico |

En el **certificado** no se verifican logos (el formato varía según la institución): se piden firma autógrafa,
sello o firma electrónica, sello institucional y foto del alumno (sección 7).

### Reglas adicionales
| Regla | Resultado si falla | Valor y origen |
|---|---|---|
| Debe tener capa de texto | rechazado | Un escaneo o foto no la tiene |
| Máximo de imágenes internas | revisar | 4 (encabezado, 2 QR, barras). La quinta suele ser una marca de agua |
| Blanco puro mínimo | revisar | 0,70: separa válidas (0,74–0,77) de escaneos (≤ 0,68) con margen |
| **Huella de origen** | revisar | productor `iText…`, creador `JasperReports…`, sin modificaciones posteriores. Las 13 válidas la cumplen; las no válidas traen `iLovePDF`, `intsig.com` (CamScanner) o nada |

Las reglas de blanco puro y huella solo mandan a `revisar`: si RENAPO cambia su generador o el diseño,
no se rechazarían constancias válidas.

### Cruce con el QR
El QR de la constancia trae: `CLAVE | CURP asociada | apellido 1 | apellido 2 | nombre | sexo | fecha | entidad de nacimiento | código de entidad de registro`.

| Dato del QR | Se compara con | Si no coincide |
|---|---|---|
| Clave | la CURP leída en el documento | revisar |
| Nombre y apellidos | el nombre leído (sin importar orden ni acentos) | revisar |
| Sexo, fecha y entidad de nacimiento | lo que codifica la propia CURP | revisar |
| Código de entidad de registro | la entidad impresa en el documento | revisar |

Esto detecta, por ejemplo, una constancia con el nombre retocado en la imagen pero no en el QR.

---

## 7. Certificado de bachillerato

**Campos que extrae Gemini:** `nombre_alumno`, `institucion`, `curp`, `folio`, `promedio`, `fecha_expedicion`,
`enlace_verificacion_impreso`.

No exige PDF digital: muchos certificados llegan escaneados.

### Elementos del formato
| Check | Nivel | Cómo se verifica |
|---|---|---|
| `codigo_qr` | **crítico** | OpenCV. Ambas variantes llevan QR |
| `institucion_legible`, `nombre_alumno_legible`, `leyenda_certificado` | crítico | Gemini (o texto del PDF) |
| `firma_autografa` | opcional* | Gemini: trazo de tinta |
| `sello_o_firma_electronica` | opcional* | texto del PDF (`SELLO DIGITAL`, `CADENA ORIGINAL`…) → si no, Gemini |
| `sello_institucional` | opcional | Gemini: sello estampado |
| `foto_del_alumno` | opcional | Gemini |
| `folio_visible` | opcional | texto del PDF → si no, Gemini |

\* Su peso real viene de las reglas por variante.

### Variante: electrónico o semielectrónico
Se decide **por lo que se ve**, no por una etiqueta suelta del modelo:

- Solo firma manuscrita → **semielectrónico**.
- Solo sello o firma electrónica → **electrónico**.
- Ambas o ninguna → se mantiene la que propuso Gemini.

La respuesta incluye `variante` (la final) y `variante_segun_modelo`.

| Variante | Se espera | No se espera | Si falla |
|---|---|---|---|
| Semielectrónico | firma autógrafa | — | revisar |
| Electrónico | sello o firma electrónica | firma manuscrita, foto | revisar |

### Validaciones del QR y del enlace
| Regla | Si falla |
|---|---|
| El QR apunta a un dominio conocido (`qr_dominios`) | revisar |
| El QR contiene un enlace | revisar |
| Si el QR trae una CURP, coincide con la del documento | revisar |
| El enlace impreso en el documento apunta al mismo dominio que el QR | revisar |

Dominios conocidos (de los ejemplos reales): `www.pace.sep.gob.mx`, `siseems.sems.gob.mx`,
`www.acuerdo286.sep.gob.mx`, `siged.sep.gob.prepa-enlinea.mx` (este último **no** es `.gob.mx`: pendiente de
confirmar).

Los enlaces del QR y el impreso se muestran **clickeables** en la interfaz. Los parámetros de la URL
(`curp`, `id_alumno`, `promedio`, `plantel`…) se muestran desglosados.

---

## 8. Validación de la CURP (`reglas_curp.py`)

No usa IA. A la clave leída se le aplica:

1. **18 caracteres.**
2. **Estructura:** letra + vocal + 2 letras, fecha `AAMMDD`, sexo `H/M/X`, entidad válida, 3 consonantes,
   homoclave y dígito.
3. **Fecha de nacimiento** real y no futura (el siglo sale de la homoclave: dígito → 1900, letra → 2000).
4. **Dígito verificador** recalculado con el algoritmo oficial.

**Corrección de lectura:** si la IA leyó `O` o `I` donde solo caben dígitos (fecha y dígito verificador) y con
`0` o `1` la CURP pasa **todas** las reglas, se da por válida y se informa en `corregida_desde`.

---

## 9. Qué devuelve (resumido)

```json
{
  "archivo": "CURD_25-02-04.pdf",
  "tipo": "curp",
  "resultado": "aceptado",
  "motivos": [],
  "campo_clave": {"campo": "clave", "valor": "SOGA060701HHGTRLA7",
                  "validacion": {"valida": true, "entidad": "Hidalgo", "fecha_nacimiento": "2006-07-01", "sexo": "H"}},
  "campos": {"clave": "…", "nombre": "…", "entidad_registro": "…"},
  "checks": {"codigo_qr": {"nivel": "critico", "presente": true, "fuente": "codigo", "evidencia": "QR decodificado"}},
  "captura": {"formato": "pdf", "digital_pdf": true, "blanco_puro": 0.772, "productor": "iText 2.1.7 by 1T3XT",
              "creador": "JasperReports (report2)", "fecha_creacion": "…", "fecha_modificacion": "…"},
  "qr": {"detectados": 1, "leidos": ["…"],
         "detalle": [{"contenido": "…", "datos": {"nombre": "ALAN YAHIR", "apellido_paterno": "SOTO"}}]}
}
```

Cada check informa su **fuente** (`codigo`, `texto_pdf` o `gemini`) y su **evidencia**, para saber en qué se
basó la decisión.

---

## 10. Dónde y cómo corre

| Pieza | Detalle |
|---|---|
| **Cloud Run** | Servicio `validar-documentos`, región `us-central1`. Contenedor con FastAPI |
| **Recursos** | 2 GiB de memoria, 4 solicitudes simultáneas por instancia, hasta 3 instancias, timeout 120 s |
| **Acceso** | Privado, con **Identity-Aware Proxy (IAP)**: se abre la URL de Cloud Run y Google pide iniciar sesión; solo entran las cuentas autorizadas (`roles/iap.httpsResourceAccessor`) |
| **Gemini** | Vertex AI, con la cuenta de servicio del contenedor (sin claves en el código) |
| **Almacenamiento** | Ninguno: los documentos se procesan y no se guardan |
| **Interfaz de pruebas** | `interfaz.html`, servida en `/` por el mismo servicio |

### Variables de entorno
| Variable | Valor actual | Qué controla |
|---|---|---|
| `GCP_PROJECT` | `validador-documentos-api` | Proyecto de Vertex AI |
| `GEMINI_THINKING_BUDGET` | `0` | Razonamiento del modelo apagado |
| `GEMINI_MODEL` | (por defecto `gemini-2.5-flash`) | Modelo de Gemini |
| `GCP_LOCATION` | (por defecto `us-central1`) | Región de Vertex AI |
| `GEMINI_PDF_COMO_IMAGEN` | (por defecto activado) | `0` envía siempre el PDF original |

### Uso
- **Pruebas manuales:** abrir `https://validar-documentos-460153897690.us-central1.run.app` e iniciar sesión con una cuenta autorizada.
- **Desde otro sistema:** con IAP activo, una integración automática necesita autenticarse ante IAP (una cuenta
  de servicio con acceso en IAP y un token emitido para él). Pendiente de definir cuando haya un sistema que lo
  consuma.
- **Cuota de Gemini:** no hay un saldo diario fijo; un 429 aparece con ráfagas o falta de capacidad. El
  servicio responde **503 "saturado"** con `Retry-After`. Pauta práctica: un documento cada 20–30 s.
- **Desplegar:**
  `gcloud run deploy validar-documentos --source . --region us-central1 --project validador-documentos-api --memory 2Gi --concurrency 4 --timeout 120 --no-allow-unauthenticated --update-env-vars GCP_PROJECT=validador-documentos-api,GEMINI_THINKING_BUDGET=0`
  (`--update-env-vars` y no `--set-env-vars`: este último borra las demás variables, por ejemplo `GEMINI_MODEL`)

---

## 11. Con qué se calibró

| Conjunto | Cantidad | Resultado |
|---|---|---|
| Constancias de CURP válidas | 13 (2 modelos: actual y SEGOB) | 13 aceptadas |
| Constancias no válidas | 6 (escaneos, CamScanner, iLovePDF) | 6 rechazadas |
| Certificados | 6 (4 semielectrónicos, 2 electrónicos) | 5 aceptados, 1 a revisar (enlace impreso distinto del QR) |

Además hay 59 tests automáticos (`tests/`) que corren sin Gemini ni credenciales.

---

## 12. Límites y pendientes

- **Migración de modelo antes del 20/10/2026:** `gemini-2.5-flash` se retira ese día. Candidato:
  `gemini-3.8-flash` con razonamiento apagado, en la región `global` (`GEMINI_MODEL` y `GCP_LOCATION`).
  Volver a correr todos los ejemplos después del cambio.
- **Sin ejemplos adulterados:** no hay documentos con datos retocados. Las reglas que los detectarían
  (cruce con el QR, huella de origen) solo se probaron con tests.
- **Muestra chica en certificados** (6, sin negativos). Las reglas por variante son provisorias.
- **Dominio `siged.sep.gob.prepa-enlinea.mx`** sin confirmar como oficial.
- **No incluido:** verificación contra RENAPO o SEP, listas negras de dominios, Document AI.

---

## 13. Mapa de archivos

| Archivo | Qué hace |
|---|---|
| `validar.py` | API: `/`, `/health`, `/tipos`, `/validar`. Orquesta los pasos |
| `composicion.py` | PDF de varias páginas: qué documento hay en cada página y extracción de las del documento pedido |
| `captura.py` | Paso 1: análisis por código (pypdf, pdfium, OpenCV) y regla de envío a Gemini |
| `motor_gemini.py` | Paso 2: arma prompt y esquema, llama a Gemini |
| `decision.py` | Paso 3: combina, cruza y decide |
| `reglas_curp.py` | Validación de la CURP, lectura del QR de la constancia, entidades |
| `config_documentos.py` | **Qué exige cada documento:** campos, checks, niveles, umbrales, dominios |
| `motor_documentai.py` | Motor alternativo, preparado pero sin implementar |
| `interfaz.html` | Página de pruebas manuales |
| `tests/` | Tests automáticos (sin Gemini) |
| `RESUMEN.md` | Versión corta para presentar |
