# Result review: local_extract: aviso de valores sin respaldo y campos de línea por título

## Review level

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no aplica (sin dependencias, sin E/S nueva; regex lineales revisadas por el juez A)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test | `line_check.Grounding`, meta `ungrounded_keys` |
| REQ-002 | sí | test | 4 tests existentes intactos |
| REQ-003 | sí | test + humo | solo campos en singular (F1) |
| REQ-004 | sí | test | plural nunca se recorta (F1) |
| REQ-005 | sí | test | la palabra sigue valiendo como antes (F3) |
| REQ-006 | sí | review | límite «otra fila» también en CHANGELOG (F2) |

## Findings

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | `outline_copy` recortaba campos que piden varias secciones (`tools_with_lines`, `api_sections_lines`) y perdía la lista | bloqueante | menor | confirmed | solo se recorta con una palabra de sitio en singular y ninguna en plural (`_ONE_PLACE_WORDS`/`_SEVERAL_PLACES_WORDS`); palabras como all/names/outline salen del nombre; test parametrizado |
| F2 | verificación desfasada (prefijo añadido, suite en TBD, límite ausente del CHANGELOG) | bloqueante | menor | confirmed | spec, verification y CHANGELOG actualizados |
| F3 | «title: 2» sobre un front matter dejaba de valer | menor | — | suspected | la palabra genérica vale por encabezado ATX o, como antes, por estar en la ventana; test |
| F4 | respuestas normalizadas largas (ninguno, nothing, false, nunca) avisaban en falso | — | menor | suspected | añadidas a `_FILLER_WORDS`; test |
| F5 | JSON con acentos escapados (`ó`) daba falsos avisos | — | menor | suspected | `Grounding` añade las cadenas y claves decodificadas de una entrada JSON; test |
| F6 | lista con un `None` saltaba la comprobación | menor | — | suspected | se ignoran los nulos de la lista; test |
| F7 | los avisos nuevos van antes de `lines_unverified` | menor | — | suspected | aceptado: el texto de los anteriores no cambia; spec reescrito con el orden real |
| F8 | encabezado que contiene una cita («Líneas 10-20») deja una cita falsa en el valor recortado | menor | menor | confirmed | riesgo residual aceptado (raro; `check_values` lo marcaría como dudoso) |
| F9 | faltan tests de troceado, prefijo numerado y CJK | menor | — | suspected | aceptado: el post-proceso usa `content` entero y valores ya sin prefijo, caminos cubiertos por #568/#591 |

## Required follow-up

- Reforzar el prompt de `local_extract` (frontera en `PROMPT_BOUNDARIES` y fixtures regeneradas) para
  el caso «otra fila» de #586: decisión del usuario, fuera de este cambio.
