# Result review: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no aplica (sin dependencias; la clave del backend no se toca)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test | texto de la cláusula reescrito tras la revisión (F1, F2) |
| REQ-002 | sí | test | frontera 0.50.0 |
| REQ-003 | sí | test | solo se declara el cambio; nada se afloja (juez A) |
| REQ-004 | sí | test | también con el prefijo `N| ` (F4) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | «no lo deduzcas» puede hacer que un modelo pequeño deje a null resúmenes, recuentos o datos dentro de una ruta | menor | media | confirmed | cláusula nueva: «pon null en vez de suponerlo… Resumir, contar o tomar lo que el contenido sí dice, aunque vaya dentro de una ruta o de un nombre, está permitido» |
| F2 | «otra fila o elemento» podía leerse en el reduce como otro objeto parcial | — | baja | suspected | ahora «otra fila de una tabla o lista» |
| F3 | criterios de la prueba en vivo que no detectaban regresiones (null aceptado en `python_version`, `function_names`, `body_summary`) y sin caso troceado | — | media | confirmed | `rerun_after.md`: columna «Fallo si…», recuento sobre entrada no JSON, caso 6 troceado (2 trozos en el «antes»), anotar rol y modelo |
| F4 | `"12\| []"` con prefijo de línea no se decodificaba | baja | baja | confirmed | `_decode_empty_lists` quita el prefijo como `_null_placeholders`; test |
| F5 | `"[]"` en un campo de recuento vuelve como `[]`, no 0; el spec decía lo contrario | media | — | confirmed | spec corregido; riesgo aceptado (antes tampoco se corregía) |
| F6 | un `"[]"` legítimo (valor por defecto `x=[]`) pasa a lista | — | baja | suspected | aceptado: el texto queda en `decoded_keys` |

## Required follow-up

- Prueba en vivo conjunta con `scratchpad/live/rerun_after.md` antes de la release.
