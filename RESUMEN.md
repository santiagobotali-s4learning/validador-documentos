# Validador de formato de documentos: resumen

Un alumno sube su **CURP** o su **certificado de bachillerato** (PDF o imagen). El sistema responde en segundos
si el documento **tiene el formato esperado** y qué datos contiene.

> Qué hace: revisa formato y extrae datos. Qué **no** hace: verificar la autenticidad en fuentes oficiales
> (RENAPO, SEP). Eso es un paso posterior.

---

## 1. Qué devuelve

| Resultado | Significa |
|---|---|
| **Aceptado** | El formato es el esperado y todo es coherente |
| **Revisar** | Hay algo dudoso: lo mira una persona. Se indica el motivo |
| **Rechazado** | Falta algo obligatorio o no es el documento esperado |

Además entrega los **datos extraídos** (nombre, CURP, folio, promedio, etc.), el **contenido del QR** y la lista de
elementos revisados, cada uno con su evidencia.

---

## 2. Cómo funciona, de principio a fin

```
  Persona sube el archivo
          │
          ▼
  ┌──────────────────────────┐
  │ Servicio en Google Cloud │  (Cloud Run, privado)
  └──────────┬───────────────┘
             │
   ┌─────────┴──────────┐
   ▼                    ▼
 1. Revisión         2. Lectura con IA
    por código          (Gemini)
 · ¿PDF digital o     · ¿Qué documento es?
   escaneo/foto?      · ¿Están los elementos del formato?
 · Texto del PDF      · Extrae los datos (nombre, CURP…)
 · Lee el código QR
   y el de barras
   └─────────┬──────────┘
             ▼
     3. Decisión por reglas (código)
        compara todo y emite:
        aceptado / revisar / rechazado + motivos
```

**Principio de diseño:** la IA *observa* (qué ve y qué lee); el **código decide**. Así el veredicto es
repetible y explicable, y no depende de la opinión del modelo.

---

## 3. Qué se extrae y qué se valida

### Constancia de CURP
- **Se extrae:** clave CURP, nombre, entidad de registro.
- **Se valida:**
  - Que sea un **PDF digital original** (no un escaneo ni una foto).
  - Los elementos del formato oficial: leyendas, QR, código de barras, bandera, etc.
  - La **CURP en sí**: estructura, fecha real y dígito verificador.
  - Que el **QR coincida con el documento**: clave, nombre, sexo, fecha y entidad.
  - Que no tenga **marcas de aplicaciones de terceros** (por ejemplo CamScanner) ni imágenes de más.

### Certificado de bachillerato
- **Se extrae:** nombre, institución, CURP, folio, promedio, fecha de expedición y el enlace impreso.
- **Se valida:**
  - El **QR es obligatorio**, y se lee su contenido (con varios intentos de resolución, porque en escaneos es difícil).
  - El QR apunta a un **dominio oficial** conocido.
  - El enlace impreso coincide con el del QR, y la CURP del QR con la del documento.
  - La **variante** (electrónico o semielectrónico) y lo que corresponde a cada una:
    firma manuscrita y sello en uno, sello y firma electrónicos en el otro.

---

## 4. Dónde corre

| Pieza | Qué hace |
|---|---|
| **Cloud Run** | Ejecuta el servicio. Escala solo, no hay servidores que administrar |
| **Gemini en Vertex AI** | Lee el documento y extrae los datos |
| **Acceso privado** | Solo entran cuentas con permiso (IAM de Google Cloud) |
| **Interfaz de pruebas** | Página para subir un documento y ver el resultado, el QR y las evidencias |

El servicio **no guarda** los documentos: los procesa y responde.

---

## 5. Estado y límites

- **Prototipo.** Probado con 5 constancias de CURP (válidas y no válidas) y 6 certificados reales.
- Los criterios del certificado se calibraron con pocos ejemplos y **sin documentos adulterados**:
  hay que ampliar la muestra.
- Lo siguiente: verificar contra fuentes oficiales y listas de dominios, y afinar el modelo de IA a usar.
