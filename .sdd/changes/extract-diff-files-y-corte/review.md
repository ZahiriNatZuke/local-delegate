# Result review: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

## Review level

<!-- Level: quick (1 judge), standard (2 judges) or deep (2 judges + security reviewer + compatibility).
Minimum: standard for lite, deep for standard. The diff may raise the level, never lower it.
Judges: the judge names separated by commas or semicolons; their count must reach the level's minimum,
for example "Judges: result-reviewer-1, result-reviewer-2". -->

- Level: standard
- Judges: result-reviewer-A, result-reviewer-B
- Security reviewer: no aplica (sin entrada nueva, red, ficheros escritos ni dependencias)
- Verdict: conforms-with-notes (los dos jueces); hallazgos medios corregidos antes del PR

## Specification comparison

| Requirement | Implemented | Verified | Notes |
| --- | --- | --- | --- |
| REQ-001 | sí | test | rangos esperados contados en el propio test |
| REQ-002 | sí | test | `model_error` añadido tras la revisión |
| REQ-003 | sí | test | protege contra un predicado demasiado amplio |
| REQ-004 | sí | test | sin prueba en vivo (401 desde agentes) |
| REQ-005 | sí | test | |
| REQ-006 | sí | test | |
| REQ-007 | sí | test | también trozos cortados en la ruta de error |
| REQ-008 | sí | test | |
| REQ-009 | sí | test | añadido tras la revisión |

## Findings

<!-- Status: confirmed (both judges), suspected (one judge), escalated (judges contradict; the user
decides and the decision goes in Resolution). -->

| ID | Finding | Judge A | Judge B | Status | Resolution |
| --- | --- | --- | --- | --- | --- |
| F1 | Ahorro contado dos veces: la llamada cortada y su rehecho escribían dos filas con el fichero entero | sí | sí | confirmed | `_fold_retried_row` pliega la fila cortada en la del rehecho; test de fila única y `_accounting` |
| F2 | Con un campo de ficheros de diff, un fallo del backend o una respuesta no JSON quedaba en silencio | sí | sí | confirmed | `model_error` con `error` y `raw`, también en `warning`; test |
| F3 | `verification.md` vacío | sí | sí | confirmed | rellenado |
| F4 | En la ruta de error troceada no se revisaban los trozos cortados | sí | no | suspected | corregido: se revisan `result` y los trozos cortados |
| F5 | Posibles falsos positivos `raw` por números de otros campos | sí | sí | confirmed | aceptado como riesgo residual: solo se mira con un corte, y `check_values` solo toma citas de línea |
| F6 | Prompt con la cláusula de diff sin prueba en vivo | sí | no | suspected | aceptado: sin backend desde agentes; prueba en vivo con test-window pendiente para la sesión principal |
| F7 | `retried_calls` del rehecho sin emitir si todo sale bien | sí | no | suspected | aceptado: coherente con el troceo actual; el log lo guarda como paso `retried` |
| F8 | El test adaptado de filas de uso quedó más flojo | sí | no | suspected | corregido: el test original vuelve sin cambios y pasa |
| F9 | `renamed_keys` puede nombrar un valor sustituido por el programa | sí | no | suspected | aceptado: el aviso sigue siendo cierto sobre lo que hizo el modelo |
| F10 | Lista de ficheros sin tope | sí | no | suspected | aceptado: el campo pide la lista entera; el aviso dice cuántas secciones son |
| F11 | Singular y «modificados» reciben todos los ficheros | no | sí | suspected | corregido el singular (solo plurales); «modificados» se mantiene: en un diff todos lo están |
| F12 | Cada sección de fichero cuenta aparte en series de parches | no | sí | suspected | aceptado; el aviso dice secciones de fichero |
| F13 | Un JSON que no es objeto perdía los ficheros | no | sí | suspected | corregido; test |
| F14 | La rama del diff no revisaba las líneas del crudo cortado | no | sí | suspected | corregido |
| F15 | `not_json_cut` aunque lo no parseable no sea lo cortado | no | sí | suspected | aceptado: solo con llamadas cortadas, y el corte es la causa más probable |
| F16 | Rehacer aunque el único campo de líneas lo dé el programa | no | sí | suspected | corregido; test |
| F17 | «los 1 ficheros» en singular | no | sí | suspected | corregido: texto neutro con la cuenta entre paréntesis |

## Required follow-up

- Prueba en vivo marcada con `test-window` del prompt de diff y del rehecho tras la mezcla (no
  posible desde un agente).
