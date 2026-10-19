# Plan de mejoras

Mejoras detectadas durante las pruebas, para aplicar más adelante. Cada una indica **por qué**, **qué hacer** y
**cómo verificarla**. Estado al 14/10/2026 (revisión desplegada: `validar-documentos-00017-9l8`).

Prioridad: 🔴 urgente · 🟠 alta · 🟡 media · ⚪ baja

---

## 🔴 1. Migrar el modelo de Gemini antes del 20/10/2026
- **Por qué:** `gemini-2.5-flash` se retira el 20/10/2026. Desde ese día el servicio deja de analizar documentos.
- **Antes de migrar (obligatorio):** desplegar siempre con `--update-env-vars` en lugar de `--set-env-vars`.
  `--set-env-vars` **reemplaza todas** las variables: después de migrar, el siguiente despliegue con el comando
  viejo borraría `GEMINI_MODEL` y `GCP_LOCATION` y el servicio volvería al modelo retirado (y dejaría de andar).
  El comando correcto ya está en `FLUJO.md`, sección 10.
- **Qué hacer:**
  - Cambiar a `gemini-3.8-flash` con razonamiento apagado. Es una revisión nueva sin recompilar:
    `gcloud run services update validar-documentos --region us-central1 --project validador-documentos-api --update-env-vars GEMINI_MODEL=gemini-3.8-flash,GCP_LOCATION=global`
  - Los modelos 3.x solo están disponibles en la región `global`: confirmar que procesar datos de alumnos fuera de
    una región fija es aceptable.
  - Alternativa más barata: `gemini-3.1-flash-lite` (más rápido, algo más de lecturas dudosas que van a `revisar`).
- **Verificar:** correr los 19 CURP y los 6 certificados de a uno. Comparar con los resultados actuales (19/19 y 5+1).
- **Rollback:** volver a las variables actuales (solo sirve hasta el 20/10).

## 🟠 2. Leer también el QR del pie de la constancia de CURP
- **Por qué:** la constancia tiene 2 QR. Hoy se lee solo el de arriba (datos de la persona). El del pie, junto a la
  firma, trae un enlace oficial (`https://consultas.curp.gob.mx/CurpSP/imprimir.do?...`) y no se lee, porque la
  búsqueda se detiene en cuanto lee el primero. A escala 4 sí se lee.
- **Qué hacer:**
  - En `captura.decodificar_qr`, seguir buscando hasta leer todos los QR detectados en la página (mismo límite de
    tiempo).
  - Mostrar ambos en la interfaz. Verificar que el enlace apunte a `consultas.curp.gob.mx` (si no → `revisar`).
  - Guardar el enlace para la verificación posterior con RENAPO.
- **Verificar:** los 19 CURP. Medir cuánto sube el tiempo.

## 🟠 3. Conseguir documentos adulterados para calibrar
- **Por qué:** no hay ningún ejemplo de documento retocado. Las reglas que los detectarían (cruce QR-documento,
  texto del PDF contra imagen, huella de origen, blanco puro) solo se probaron con tests.
- **Qué hacer:** reunir casos como:
  - constancia con el nombre o la fecha cambiados en la imagen (sin tocar el QR);
  - constancia abierta y guardada en iLovePDF o Word conservando el texto;
  - constancia impresa a PDF desde el navegador;
  - captura de pantalla convertida a PDF;
  - certificado con QR de otro alumno o de un dominio falso.
- **Verificar:** que cada uno salga `revisar` o `rechazado` con el motivo correcto. Ajustar umbrales si hace falta
  (`umbral_blanco_puro`, `SIMILITUD_MINIMA_TEXTO`, `MAX_IMPORTANTES_FALTANTES`).

## 🟠 4. Cruzar más datos del QR del certificado
- **Por qué:** algunos QR de certificado (SISEEMS) traen en la URL `curp`, `nombre_alumno`, `promedio` y `plantel`.
  Hoy solo se compara la CURP.
- **Qué hacer:** comparar nombre (con la misma tolerancia que en la CURP), promedio y plantel con lo leído en el
  documento. Diferencia → `revisar`.
- **Ojo:** Gemini no siempre lee `promedio` e `institucion` igual (formato "7.8" contra "7.8 Siete punto ocho").
  Normalizar antes de comparar.

## 🟡 5. Definir los casos dudosos de certificados
- **Dominio `siged.sep.gob.prepa-enlinea.mx`:** no termina en `.gob.mx`. Confirmar si es oficial; si no, sacarlo
  de `qr_dominios`.
- **Cómo se reconoce un dominio oficial:** hoy, solo por **coincidencia exacta** con la lista `qr_dominios`
  (4 dominios sacados de los 6 ejemplos). Un certificado auténtico de otro sistema, o el mismo dominio sin `www`,
  va a `revisar`. Propuesta:
  - aceptar además cualquier dominio que **termine en `.gob.mx`** (en México solo lo registran dependencias de
    gobierno), comparando la terminación completa para que `sep.gob.mx.sitio-falso.com` no pase;
  - mantener la lista para los casos que no son `.gob.mx` (como `prepa-enlinea.mx`);
  - más adelante, reemplazarla por la lista buena / lista negra de dominios que ya existe.
  - Verificar con los 6 certificados y con dominios de prueba falsos.
- **Certificado `24-04-16` (Preparatoria Abierta):** tiene firma manuscrita y sello digital a la vez, y el
  enlace impreso apunta a otro dominio que el QR. Hoy va a `revisar`. Decidir si es normal en ese sistema.
- **Variantes:** confirmar con los documentos cuáles de los 6 son electrónicos y cuáles semielectrónicos
  (hoy el sistema dice 2 y 4).
- **Ampliar la muestra:** más certificados de distintas instituciones, incluidos digitales con capa de texto
  (todavía no hay ninguno; la regla de envío a Gemini para esos casos no está probada).

## ✅ 6. Acceso para que otras personas prueben (hecho el 14/10/2026)
- **Identity-Aware Proxy (IAP) activo.** Link: `https://validar-documentos-460153897690.us-central1.run.app`.
  Entran con su cuenta de Google: `santiago.botali@`, `patricia.quintero@` y `jonatan.loaiza@s4learning.com`.
- **Para sumar a alguien:**
  1. Agregarlo como usuario de prueba en la pantalla de consentimiento (consola: Google Auth Platform → Audience).
  2. Darle acceso en IAP:
     `gcloud iap web add-iam-policy-binding --member=user:CORREO --role=roles/iap.httpsResourceAccessor --region=us-central1 --resource-type=cloud-run --service=validar-documentos --project=validador-documentos-api`
- **Después de cada despliegue:** confirmar que sigue `Iap Enabled: true`
  (`gcloud run services describe validar-documentos --region us-central1 --project validador-documentos-api`).
- **Volver atrás si un cambio sale mal:**
  `gcloud run services update-traffic validar-documentos --region us-central1 --project validador-documentos-api --to-revisions REVISION-ANTERIOR=100`
- Más detalle de las opciones evaluadas al final de este documento.

## 🟡 7. Guardar las pruebas de regresión en el proyecto
- **Por qué:** las pruebas con Gemini sobre los ejemplos reales se hicieron con scripts temporales. Después de cada
  cambio hay que repetirlas a mano.
- **Qué hacer:** un script `scripts/regresion.py` que recorra `ejemplosCURP/` y `ejemplosCERTIFICADOS/` de a uno
  (con pausa por la cuota), compare con el resultado esperado según la carpeta y muestre una tabla.
  Correrlo antes de cada despliegue.

## 🟡 8. Registro de uso y cuota de Gemini
- Anotar por día cuántos documentos se prueban y si aparecen errores 429 o 503, para conocer el límite real.
- Configurar una alerta en Cloud Monitoring para los errores 429 de Vertex AI.

## ⚪ 9. Privacidad en los logs
- Cuando algo falla, el servicio escribe el **nombre del archivo** en los logs de Cloud Run. Si los nombres
  pueden contener datos personales, registrar solo un identificador.

## ⚪ 10. Documentación
- Actualizar `README.md`: está desactualizado (no menciona la interfaz, las variables de entorno nuevas, los
  ejemplos ni los `.md` nuevos).
- Guardar la guía de la interfaz (qué es cada sección) como `GUIA_INTERFAZ.md`.
- Mostrar en la interfaz de dónde salió cada campo (`campos_fuente`: texto del PDF o Gemini).

## ⚪ 11. Limitaciones conocidas a revisar más adelante
- **Nombres largos:** en la comparación entre la imagen y el texto del PDF, un cambio de una sola letra en un
  nombre largo queda dentro de la tolerancia (≥ 0,93) y no se detecta.
- **Blanco puro:** el mismo PDF mide distinto en Windows y en Cloud Run (unas milésimas). El umbral 0,70 tiene
  margen, pero no conviene subirlo.
- **Huella de origen:** si RENAPO cambia su generador de PDF, todas las constancias nuevas irían a `revisar`.

## ⚪ 12. Siguiente etapa (fuera del alcance actual)
- Verificación contra RENAPO y SEP (usando los enlaces de los QR).
- Listas blanca y negra de dominios de certificados.
- Document AI como motor alternativo (`motor_documentai.py` ya tiene el contrato).

---

## Probar el prototipo desde otro lugar

**No hace falta tener nada corriendo en tu computadora.** El servicio vive en Cloud Run las 24 horas: se enciende
solo cuando llega una solicitud. El comando `gcloud run services proxy` que usás es solo una forma de
**autenticarte vos** para entrar a un servicio privado. Si cerrás tu computadora, el servicio sigue funcionando.

El obstáculo para que otra persona lo pruebe es que **el servicio es privado** (sin permiso responde 403).
Opciones:

| Opción | Qué necesita el que prueba | Esfuerzo | Comentario |
|---|---|---|---|
| **A. Permiso IAM + proxy** | Cuenta de Google, gcloud instalado, correr el comando del proxy | Bajo para vos, alto para el que prueba | Solo para gente técnica |
| **B. Identity-Aware Proxy (IAP)** ✅ activo | Solo el navegador: entra con su cuenta de Google | Medio, una sola vez | **Elegida e implementada.** La interfaz ya está servida por Cloud Run en `/`; no hace falta Vercel |
| **C. Interfaz en Vercel + función intermedia** | Solo el navegador | Alto | Ver abajo |
| **D. Público con contraseña propia** | Solo el navegador y la clave | Medio | Cualquiera con la clave consume tu cuota; con datos de alumnos no es lo ideal |

### Sobre Vercel
- Si subís solo la página (`interfaz.html`) a Vercel, **no funciona**: el navegador del que prueba no puede
  autenticarse ante Cloud Run, que es privado.
- Para que funcione, hace falta una **función en Vercel que haga de intermediaria**: recibe el archivo, se
  autentica ante Google con una cuenta de servicio con permiso `roles/run.invoker` y reenvía el archivo a Cloud
  Run. Implica guardar una credencial de Google en Vercel y **proteger la página de Vercel** (si no, cualquiera
  con la URL usa el servicio).
- **Límite a verificar:** las funciones de Vercel tienen un tope de tamaño del cuerpo de la solicitud (del orden de
  4,5 MB). Uno de los certificados de ejemplo pesa 5,4 MB y no pasaría.
- **Conclusión:** Vercel suma complejidad sin agregar nada que Cloud Run no tenga ya. Para que otros prueben,
  la opción B (IAP) es más simple y más segura.
