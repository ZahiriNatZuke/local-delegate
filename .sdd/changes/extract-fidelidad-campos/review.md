# Result review: local_extract: aviso de valores sin respaldo y campos de línea por título

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B, independent-reviewer-609
- Security reviewer: no aplica (sin dependencias ni E/S nueva)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-003 | sí | test + humo | recorte solo sin duda (F1, F10) |
| REQ-004 | sí | test | plurales es/en y `each`/`cada` no son copia (F10) |
| REQ-005 | sí | test | título genérico solo sobre la línea citada (F12) |
| REQ-006 | sí | review | docs sin `ungrounded_keys` (F11) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `outline_copy` recortaba campos que piden varias secciones (`tools_with_lines`) | bloqueante | menor | confirmed | palabra de sitio en plural: no es copia |
| F2 | verificación desfasada | bloqueante | menor | confirmed | artefactos actualizados |
| F3 | «title: 2» sobre un front matter dejaba de valer | menor | — | suspected | la palabra sigue valiendo en la ventana; test |
| F10 | (revisión independiente) sujeto plural junto a palabra de sitio singular (`tools_section_line`, `tool_heading_line`, `pasos_heading_line`) recortaba y perdía la lista; `capitulos_con_linea` y `line_of_each_heading` daban un falso «esquema copiado» | bloqueante | — | confirmed | recorte solo con sujeto singular y coincidencia de palabra entera; con duda se avisa; plurales en español y `each`/`cada` piden varios sitios; tests con los cinco nombres |
| F11 | (revisión independiente) `ungrounded_keys` daba avisos falsos en traducciones, clasificaciones, fechas, paráfrasis y palabras con guion | bloqueante | — | confirmed | retirado entero (código, i18n, tests, docs); #586 va al cambio del prompt |
| F12 | (revisión independiente) «Título: línea N» se aceptaba con cualquier encabezado en la ventana de tolerancia | menor | — | confirmed | solo un encabezado del esquema (fuera de bloques de código) en las líneas citadas; tests |
| F8 | encabezado con una cita dentro deja una cita falsa en el valor recortado | menor | menor | confirmed | riesgo residual aceptado |

## Required follow-up

- #586: cambio del prompt de `local_extract` en `fix/extract-prompt-sin-relleno` (`Closes #586`).
