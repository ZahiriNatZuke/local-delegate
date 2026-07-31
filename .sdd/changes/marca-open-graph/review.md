# Revisión del resultado: Marca única y metadatos sociales en la landing

## Veredicto

`conforms-with-notes` — los ocho requisitos se cumplen, verificados hoy por ejecución. La nota es
**de proceso**: la traza SDD se rellenó a posteriori.

## Comparación contra la especificación

| Requisito | Implementado | Verificado | Notas |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | Los dos ficheros dan el **mismo SHA-256**. Un test los compara byte a byte. |
| REQ-002 | sí | sí | `_load_favicon()` lee el recurso del paquete; el icono ya no está inline. |
| REQ-003 | sí | sí | Comprobado al implementar; el panel sirve el icono en instalación real. |
| REQ-004 | sí | sí | Doce `og:*`, `canonical`, `theme-color` y `twitter:card=summary_large_image` en el HTML servido. |
| REQ-005 | sí | sí | IHDR de la imagen publicada: **1200×630**, igual que lo declarado. |
| REQ-006 | sí | sí | `og-image.src.html` versionado con el procedimiento dentro. |
| REQ-007 | sí | sí | Ausente del build y **404** en producción. |
| REQ-008 | sí | sí | Test que exige que la regla del resalte no mencione `--local` y que el `span` cubra solo «la nube», en los dos idiomas. |

## Hallazgos

1. **De proceso, y es el motivo de este cierre:** los artefactos se commitearon en plantilla. El
   trabajo salió bien —incluidos los tests verificados al revés— pero la especificación no lo
   guió.

2. **De alcance, y sigue vivo:** la corrección del amarillo se aplicó al **titular** y no al
   **botón de idioma**, que sigue usando `--local` para su estado `aria-pressed="true"`. Es la
   misma mezcla de significado. No es regresión de este cambio, pero sí una superficie que este
   cambio no contó — el mismo patrón de «contar las superficies antes de arreglar una» que el repo
   ya pagó. Se ataca en su propio cambio.

3. **Ninguno de corrección o seguridad.**

## Seguimiento requerido

Ninguno antes del cierre. El fleco del botón de idioma se trabaja aparte y queda registrado en
`verification.md` y en el backlog.
