# Specification: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

## Summary

`local_extract` con `path` y un campo de líneas deja de perder ficheros de un diff y deja de
devolver en silencio un JSON cortado por `max_tokens`.

## Requirements

- **REQ-001** — Con `path` a un diff unificado, un campo que solo pide los ficheros y sus líneas
  (`ficheros_con_lineas`, `files_with_lines`, `archivos_y_lineas`, `rutas_con_lineas`) vuelve con
  una entrada `ruta: primera-última` por fichero del parche, en orden, aunque el modelo nombre solo
  algunos; troceado o en una sola llamada.
  - Request: "local_extract sobre un .patch grande devuelve solo el primer fichero"
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_every_file_of_a_chunked_diff_comes_back
- **REQ-002** — Ese valor por programa lo dice `_local_delegate.diff_files` (`fields`, `files`,
  `notice`), sin `warning`, y sobrevive a una respuesta del modelo que no es JSON o no es un
  objeto; en ese caso el error del modelo o del backend viaja en `_local_delegate.model_error`
  (`error`, `raw`) y en `warning`, nunca en silencio. Un nombre en singular
  (`fichero_con_lineas`) no recibe la lista de todos los ficheros.
  - Request: derived: quien llama debe saber que el valor no es del modelo y no recibir un error
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_the_diff_files_survive_an_answer_that_is_not_json
- **REQ-003** — Otro campo de líneas sobre un diff, un fichero que no es diff o un diff pasado con
  `text=` no cambian: el valor es el del modelo.
  - Request: derived: no tocar lo que no pide ficheros
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_another_location_field_over_a_diff_keeps_the_models_value
- **REQ-004** — Con un diff y un campo de líneas, el prompt avisa de que los números de `@@` no son
  líneas del parche (`_DIFF_LINES_CLAUSE`, como #582).
  - Request: derived: el modelo confundía los números de las cabeceras con líneas del parche
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_single_call_diff_is_answered_by_program_too
- **REQ-005** — Si la llamada única con un campo de líneas se corta por `max_tokens` y la entrada se
  puede partir, se rehace troceada en mitades y los campos de líneas se unen por programa.
  - Request: "Se esperaba trocear la entrada"
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_cut_single_call_is_retried_in_halves
- **REQ-006** — Si aun así no hay JSON, el error dice que la salida se cortó por `max_tokens`
  (`mcp.extract.not_json_cut`, es y en); sin corte se mantiene `mcp.extract.not_json`.
  - Request: "o un error/aviso explícito, nunca JSON roto en silencio"
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_cut_call_too_small_to_split_says_max_tokens
- **REQ-007** — Las líneas citadas que no casan con el fichero van a `lines_unverified` también en
  una respuesta cortada (como `raw: N`), en el error y en un trozo cortado que se queda fuera.
  - Request: "líneas inventadas"
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_cut_chunk_beside_good_ones_has_its_lines_checked
- **REQ-008** — Una respuesta cortada sin campos de líneas no se rehace.
  - Request: derived: sus valores compiten entre trozos; no hay unión por programa
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_cut_answer_without_location_fields_is_not_retried
- **REQ-009** — La llamada cortada y su rehecho son una sola fila de uso: `chunks` cuenta todas las
  llamadas al backend, la cortada va como primer paso `retried`, y el fichero leído en el
  servidor se cuenta una vez en `_accounting`. Si el único campo de líneas lo da el programa, la
  llamada cortada no se rehace.
  - Request: derived: revisión de resultado (doble cuenta de ahorro en el panel)
  - Verify: test tests/test_extract_diff_files_and_cut.py::test_a_retried_call_is_one_usage_row_that_reads_the_file_once

## Acceptance scenarios

### Scenario: diff de 30 ficheros troceado

- **Given** un `.patch` de 30 ficheros que no cabe en una llamada
- **When** se pide `ficheros_con_lineas` y el modelo nombra solo el primer fichero de cada trozo
- **Then** el valor trae los 30 ficheros con su rango exacto y `diff_files.files` es 30

### Scenario: Markdown con muchas líneas pedidas

- **Given** un Markdown de ~29 K caracteres (una sola llamada)
- **When** la respuesta se corta por `max_tokens`
- **Then** la llamada se rehace troceada y vuelven todas las líneas, sin error

## Edge cases and failure behavior

- Entrada de menos de `2 × CHUNK_MIN_CHARS`: no se rehace; error con `max_tokens`.
- Todo cortado, también el reduce: error `not_json_cut` con `truncated` y `lines_unverified`.

## Non-functional requirements

- Sin dependencias nuevas; textos al usuario en es y en; código en inglés.

## Non-goals

- Campos por hunk, resúmenes de diff, subir de versión.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
