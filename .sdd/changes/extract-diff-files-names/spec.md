# Specification: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Summary

Sobre un diff con `path`, más nombres de campo que piden ficheros (y sus hunks) reciben su valor
por programa, y los casos que no se pueden responder así lo dicen en `warning`.

## Requirements

- **REQ-001** — Un campo de líneas que pide los ficheros y sus hunks (`ficheros_y_hunks_con_lineas`,
  `files_and_hunks_with_lines`, `archivos_y_hunks_con_lineas`) recibe, por programa, una entrada por
  fichero `ruta: primera-última (hunks: a-b, c-d)` en líneas del parche, troceado o no; lo dice
  `_local_delegate.diff_files`. `hunks_with_lines` a secas o un singular no cambian.
  - Request: "un campo que pide ficheros + hunks debe dar fichero y rango de cada hunk dentro del patch"
  - Verify: test tests/test_extract_diff_files_names.py::test_files_and_hunks_of_a_92_kb_patch_come_back_by_program
- **REQ-002** — `changed_files_with_lines` y `modified_files_with_lines` son campos de líneas que
  piden los ficheros; `lines_changed`, `changed_lines` o `changed_files_count` siguen siendo recuentos.
  - Request: derived: variantes en inglés pedidas en el encargo (`changed_files_with_lines`)
  - Verify: test tests/test_extract_diff_files_names.py::test_changed_files_with_lines_over_a_chunked_diff
- **REQ-003** — Un fichero `.patch` o `.diff` se lee como diff aunque no empiece por una cabecera de
  parche (preámbulo antes del primer `diff --git`); sin ese sufijo, manda el principio (#499).
  - Request: "si la entrada se detecta como diff cuando empieza con cabeceras de git format-patch [...] o cuando el fichero es .patch/.diff"
  - Verify: test tests/test_extract_diff_files_names.py::test_a_patch_with_a_preamble_is_still_read_as_a_diff
- **REQ-004** — Un `.patch`/`.diff` sin cabeceras de fichero, con un campo de ficheros, devuelve un
  `warning` que dice que el programa no encontró ficheros y el valor es del modelo.
  - Request: "si no se puede, un warning que lo diga"
  - Verify: test tests/test_extract_diff_files_names.py::test_a_patch_without_file_headers_says_so
- **REQ-005** — Un campo de líneas que el programa no responde y queda en `null` en todos los trozos
  de un diff añade al `warning` qué nombres sí se responden por programa.
  - Request: "que nunca vuelva un null silencioso sobre un diff troceado"
  - Verify: test tests/test_extract_diff_files_names.py::test_a_null_location_field_over_a_chunked_diff_names_the_program_fields

## Acceptance scenarios

### Scenario: patch grande con ficheros nuevos

- **Given** un `.patch` de ~92 KB y 14 ficheros, 6 nuevos con hunks `@@ -0,0 +1,N @@` largos
- **When** se pide `ficheros_y_hunks_con_lineas` y el modelo no da nada en ningún trozo
- **Then** vuelve cada fichero con su rango y el de cada hunk, sin `warning`

## Edge cases and failure behavior

- Un Markdown que enseña un diff no se lee como diff.
- Un `.patch` sin cabeceras: `null` con `warning`.

## Non-functional requirements

- Recorrido lineal del parche, sin regex nuevas con backtracking; textos es+en en el catálogo.

## Non-goals

- Cambiar `local_explain_code` o el troceado.

## Traceability

Every requirement maps to a task in `plan.md` and to one row in `verification.md`;
`personal-harness sdd check <slug>` proves it.
