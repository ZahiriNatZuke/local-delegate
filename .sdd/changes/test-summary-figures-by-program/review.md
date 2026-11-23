# Result review: Resumen de salidas de tests: totales y versión por programa, y aviso de negación sin falsos positivos

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-a, result-reviewer-b
- Security reviewer: no — solo añade texto tras el resumen; sin red, rutas ni secretos nuevos; las regex nuevas las revisaron los dos jueces (lineales, acotadas)
- Verdict: conforms-with-notes

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | yes | yes | la coma de una lista de categorías no corta (H1); el test aísla la coma (H2) |
| REQ-002 | yes | yes | faltan cifras compuestas (doscientos, dozen): límite anotado |
| REQ-003 | yes | yes | errors propia; «fallos» abarca fallos y errores |
| REQ-004 | yes | yes | la línea que cuenta va en medio en el test (H7) |
| REQ-005 | yes | yes | es y en con test; separador de cargo propio (H4); cita literal anclada a cifras (J2-1) |
| REQ-006 | yes | yes | versiones nombradas en la entrada no avisan (H3); en vivo no se vio el aviso |
| REQ-007 | yes | yes | suite completa y CI; 6 tests de hooks fallan igual sin el cambio en el worktree local |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| H1 | La coma cortaba las listas «fallos, saltos ni errores» (regresión) | A1 | — | suspected | arreglado: `_is_a_list` y test |
| H2 | El test de la coma no la aislaba («cuatro» ya cortaba) | A2 | — | suspected | arreglado: «Sin fallos, con pruebas omitidas» |
| H3 | Versión nombrada en otro sitio de la entrada daba aviso falso | A3 | — | suspected | arreglado: toda versión de la entrada cuenta como real |
| H4 | Partes de cargo unidas con «, » | A4 | — | suspected | arreglado: separador del runner |
| H5 | La línea no queda la última en summarize | A5 | — | suspected | spec ajustado: «tras el resumen, entre sus avisos» |
| H6-H8 | Controles y test hostil poco finos | A6-A8 | J2-7 | confirmed | arreglados (control «ni omitidas», línea que cuenta en medio, cabecera de menos de 400 caracteres) |
| H9 | «Ninguna de las dos pruebas fue omitida» no avisa | A9 | — | suspected | aceptado en non-goals |
| H10 | Log de pytest limpio en lint va por `_lint_no_findings` | A10 | — | suspected | aceptado: esa respuesta ya cita la línea de totales |
| H11 | `totals()` se calcula varias veces | A11 | — | suspected | aceptado: lineal, sin coste visible |
| H12 | Faltaban tests de más de 3 líneas y de Go | A12 | — | suspected | añadidos |
| J2-1 | «216 passed» contaba como cita de `16 passed` | — | B1 | suspected | arreglado: `quotes_parts` anclado a cifras |
| J2-2 | Lista con coma avisaba sobre «No failures, skipped 3» | — | B2 | suspected | arreglado: una cifra tras la categoría la cuenta |
| J2-3 | T4 sin CHANGELOG ni wiki | — | B3 | suspected | rechazado: el juez vio un diff de `src tests`; CHANGELOG y wiki están en el primer commit |
| J2-4/J2-5 | Cifras compuestas; «once» inglés | — | B4-B5 | suspected | aceptado como límite |
| J2-6 | `_PYTHON_IN_TEXT` corre sobre todo el texto | — | B6 | suspected | aceptado: lineal y con tope de 2 MB |
| J2-8 | Sin test en inglés | — | B8 | suspected | añadido |
| J2-9 | Nombres de test viejos en verification.md | — | B9 | suspected | corregido |

## Required follow-up

- Ninguno bloqueante. Límites anotados: cifras compuestas en letras y «once» inglés.
