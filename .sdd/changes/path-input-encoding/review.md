# Result review: Lectura con path: ficheros que no son UTF-8 y falsos «datos inventados» con m²/m³ (#672)

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no — no toca autenticación, secretos ni permisos; la entrada no confiable solo pasa por `bytes.decode` y por las expresiones que ya tenía `grounding`
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | sí | test del BOM de UTF-8 añadido tras la revisión (juez A) |
| REQ-002 | sí | sí | test del BOM de UTF-16 con cuerpo roto añadido (jueces A y B) |
| REQ-003 | sí | sí | los dos errores de extract llevan ya la codificación (juez A); test del resumen estructurado y del error de extract |
| REQ-004 | sí | sí | la repro pasa con cualquiera de los dos arreglos; los tests puros de grounding los separan |
| REQ-005 | sí | sí | |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | verification.md sin rellenar y puertas spec y plan pendientes | sí | sí | confirmed | rellenado; puertas pasadas; desviación de orden escrita en verification.md |
| F2 | errores de extract sin la codificación | sí | no | suspected | arreglado con `_with_input_encoding_meta` y test |
| F3 | un solo byte inválido en un fichero casi UTF-8 lo lee entero como cp1252 | sí | sí (H4) | confirmed | aceptado y escrito como riesgo; el aviso lo dice |
| F4 | ramas troceadas sin test propio | sí | no | suspected | test del estructurado añadido; el resto revisado a mano |
| F5 | el filtro de solo letras deja de ver un cambio de unidad (m³ por m²) | no | sí | suspected | aceptado: esa revisión es de idioma, no de unidades; escrito como riesgo |
| F6 | binario o UTF-16 sin BOM: el aviso pide convertir a UTF-8 | no | sí | suspected | aceptado; no peor que antes; fuera de alcance |
| F7 | ContextVar sin restaurar en los tests | sí | sí | confirmed | fixture autouse que la reinicia |

## Required follow-up

- Ninguno bloqueante. Posible mejora futura: aviso de «binario o UTF-16 sin BOM» al ver bytes NUL.
