# Verification: local_extract: las líneas las calcula el programa y el esquema tiene tipos por campo (#692, #694, #696, #697, #698)

## Environment

- Revision: rama `feat/extract-locate-b` (sobre main a776da37 con `origin/feat/extract-locate-a` eaad9b4e mezclado: T1–T4, T9 y el lexer rápido de TS), commits d58cd50e y, tras la segunda revisión, f55e57ac (rendimiento, REQ-022) y el de sus hallazgos (NBSP del lexer, `role_reason` con tabla).
- Relevant runtime and tool versions: Windows 11, CPython 3.11.15 (uv), pytest con xdist `-n 2`, ruff del entorno del proyecto; backend real de la PC para la prueba en vivo (llama-swap en 127.0.0.1:9292, modelos `gemma3-4b` y `qwen36-35b-a3b`).

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_extract_locate_server.py::test_model_numbers_never_reach_the_value` + mutante M2 | pass | verde; M2 (copiar el `start` del modelo) lo pone en rojo |
| REQ-002 | `test_extract_locate_server.py::test_every_location_value_has_the_new_shape` | pass | verde en los caminos índice, selección, ancla, diff y troceado |
| REQ-003 | `tests/test_locate_index_python.py` | pass | verde; M1 (sumar 1 a las líneas) lo pone en rojo |
| REQ-004 | `tests/test_locate_index_ts.py` | pass | verde; `test_a_unicode_blank_is_skipped_like_a_space` (NBSP, U+2003, U+3000 antes de `{`, `}`, regex y cadena) y M12 lo pone en rojo |
| REQ-005 | `test_locate_markdown_ids.py::test_sections_end_before_the_next_heading_of_same_or_higher_level`, `::test_blocks_at_a_line` | pass | verde |
| REQ-006 | `test_extract_diff_files_names.py` y `test_extract_diff_files_and_cut.py` reescritos | pass | 31 + 27 verdes; mismos rangos que antes en la forma `{name, start, end}` (con `hunks`) |
| REQ-007 | `test_locate_markdown_ids.py::test_sixty_requirements_get_their_exact_lines`, `test_extract_locate_server.py::test_the_696_fields` | pass | verdes; el de servidor (añadido tras la revisión) ancla a mitad de la tabla y en el título y da la tabla entera y la sección exactas |
| REQ-008 | `tests/test_locate_fields.py` (parametrizado) | pass | verde; M4 y M5 lo ponen en rojo |
| REQ-009 | `test_extract_locate_server.py::test_index_only_fields_never_reach_the_backend`, `::test_program_only_row_is_written`, `::test_a_singular_heading_field_gets_one_heading` | pass | verdes; M6 (índice entero a un singular) lo pone en rojo |
| REQ-010 | `test_extract_locate_server.py::test_selected_names_get_the_index_lines`, `::test_a_name_outside_the_index_is_unlocated` | pass | verdes |
| REQ-011 | `tests/test_locate_anchor.py`, `test_extract_locate_server.py::test_a_jsdoc_anchor_is_never_returned_as_code` | pass | verdes; M3 (ancla sin mayúsculas) lo pone en rojo |
| REQ-012 | `test_extract_line_numbers.py::test_no_line_number_reaches_the_model`, `::test_the_catalogue_is_left_out_when_too_long` | pass | verdes |
| REQ-013 | `test_extract_line_numbers.py::test_chunked_anchors_are_resolved_against_the_whole_file` | pass | verde; M9 (ancla de trozo solo contra el fichero entero) lo pone en rojo |
| REQ-014 | `test_extract_locate_server.py::test_location_fields_never_go_to_the_mechanical_role` | pass | verde; en vivo, el caso B fue al rol `code` con `role_reason.reason = location`. `::test_a_table_answered_by_program_has_no_role_reason` (fichero pequeño con tabla, todo por programa: ni la respuesta ni la fila del log llevan `role_reason`) y M13 lo pone en rojo |
| REQ-015 | `test_extract_schema.py::test_field_kinds`, `tests/test_core.py::test_json_schema_payload_types_each_field` | pass | verdes; M8 (boolean en el esquema de `list`) lo pone en rojo |
| REQ-016 | `test_extract_schema.py::test_a_boolean_in_a_list_field_is_retried_once`, `::test_a_mismatch_that_persists_is_null_and_said` | pass | verdes; M8b (validar acepta boolean en `list`) lo pone en rojo |
| REQ-017 | `test_extract_schema.py::test_output_budget`, `test_extract_locate_server.py::test_the_real_max_tokens` | pass | verdes; M7 (512 fijo) lo pone en rojo (`[512] == [2464]`) |
| REQ-018 | `test_extract_locate_server.py::test_meta_keys`, `test_extract_section_lines.py::test_the_shape_of_the_issue_is_reported` | pass | verdes; `lines_unverified`, `outline_copies` y `diff_files` ya no salen |
| REQ-019 | suite de extract, explain_code, core, summarize, i18n y catálogo con `-n 2`; `git diff --stat origin/main` de los tests que se conservan | pass | 1164 verdes (los 2 de tiempo de 1 MB se rehicieron, REQ-022); de los conservados solo cambia `test_extract_placeholder_values.py` (−14: se borra `test_a_numbered_marker_is_null`, que probaba el prefijo `N\|` retirado) |
| REQ-020 | `tests/test_extract_locate_docs.py`, `tests/test_i18n_parity.py` | pass | verdes; CHANGELOG «Sin publicar» como incompatible de la 0.54.0, README, `docs/wiki/Tools.md`, skill es/en y memoria es/en |
| REQ-021 | tabla de mutantes (abajo) | pass | 18 de 18 mutantes en rojo (M1–M17 y M8b), cada uno con el assert que lo detecta |
| REQ-022 | `test_locate_index_ts.py::test_unbalanced_braces_drop_the_index`, `test_locate_index_python.py::test_syntax_error_gives_no_index`, `test_locate_anchor.py::test_index_and_anchors_cost_grows_linearly`, `test_locate_index_ts.py::test_typescript_index_cost_grows_linearly` | pass | criterio cambiado a crecimiento lineal (spec, 2026-11-23). En la PC: 100 KB → 1 MB crece ×13,8 (índice y 407 anclas, 0,52 s) y ×11,7 (índice TS, 0,45 s), tope ×25. Mutantes M10 y M11 abajo. Entrada hostil (revisión de seguridad): `tests/test_locate_hostile_input.py` (una línea de comillas que no cierran, de `(/[`, 25 000 encabezados y una cadena de 1 500 `elif`), lineal o sin caerse; M14–M17 en rojo |

### Mutantes de REQ-021

Aplicados uno a uno en un worktree temporal (`scratchpad/mutants.py`), con su test y revertidos.

| Mutante | Fichero | Test que lo detecta | Assert que dispara |
| --- | --- | --- | --- |
| M1 sumar 1 a las líneas del índice | `locate.py` | `test_locate_index_python.py::test_functions_classes_and_methods_at_any_depth` | `AssertionError: decorated` |
| M2 dejar pasar el `start` del modelo | `server.py` | `test_extract_locate_server.py::test_model_numbers_never_reach_the_value[item0]` | `[{'end': 120}] == [{'end': 31}]` |
| M3 ancla por parecido sin mayúsculas | `locate.py` | `test_locate_anchor.py::test_blanks_are_normalized_but_case_is_kept` | `(5, None) == (None, 'not_found')` |
| M4 `classify_field` exige todas las palabras en el vocabulario | `locate.py` | `test_locate_fields.py::test_categories_by_presence[ficheros_que_cambian_con_sus_lineas]` | `frozenset() == frozenset({'files'})` |
| M5 buscar categorías tras quitar las palabras cortas | `locate.py` | `test_locate_fields.py::test_categories_by_presence[ids_con_lineas]` | `frozenset() == frozenset({'ids'})` |
| M6 índice entero a una categoría singular | `locate.py` | `test_extract_locate_server.py::test_a_singular_heading_field_gets_one_heading` | `too many values to unpack (expected 1)` |
| M7 volver a `max_tokens=512` | `server.py` | `test_extract_locate_server.py::test_the_real_max_tokens` | `[512] == [2464]` |
| M8 `boolean` en el esquema de `list` | `extract_schema.py` | `tests/test_core.py::test_json_schema_payload_types_each_field` | `'boolean' not in [...]` |
| M8b la validación acepta `boolean` en `list` | `extract_schema.py` | `test_extract_schema.py::test_a_number_fits_a_list_and_a_boolean_does_not` | `assert False` |
| M9 ancla de un trozo solo contra el fichero entero | `locate.py` | `test_extract_line_numbers.py::test_chunked_anchors_are_resolved_against_the_whole_file` | `[{'end': None}] == [{'end': 664}]` |
| M10 (REQ-022) volver a buscar el ancla línea a línea en Python (el código anterior a este arreglo) | `locate.py` | `test_locate_anchor.py::test_index_and_anchors_cost_grows_linearly` | `growth < MAX_GROWTH`: ×30,0 (1 MB en 1,31 s) |
| M11 (REQ-022) la línea de un offset contada desde el principio (`src.count("\n", 0, offset)`) | `locate_ts.py` | `test_locate_index_ts.py::test_typescript_index_cost_grows_linearly` y `test_locate_anchor.py::test_index_and_anchors_cost_grows_linearly` | `growth < MAX_GROWTH`: ×72,2 y ×74,0 (1 MB en 9,6 s) |
| M12 (REQ-004) blancos del lexer con retroceso (`(\s*)` en vez de `(\s*+)`): un NBSP antes de `{` o de `/re/` se lee como palabra | `locate_ts.py` | `test_locate_index_ts.py::test_a_unicode_blank_is_skipped_like_a_space` (los tres blancos) | `assert with_blank.unavailable_reason is None` |
| M13 (REQ-014) no borrar el `role_reason` de la regla de tablas cuando todo lo contesta el programa | `server.py` | `test_extract_locate_server.py::test_a_table_answered_by_program_has_no_role_reason` | `'role_reason' not in {'role_reason': {'role': 'long', 'reason': 'table', …}}` |
| M14 (REQ-022) sin la memoria de la comilla que no cierra (`dead`): cada comilla vuelve a recorrer la línea | `locate_ts.py` | `test_locate_hostile_input.py::test_a_hostile_line_costs_linearly[single_quote_escapes]` | `growth < MAX_GROWTH`: ×204,6 (50 KB en 22 s) |
| M15 (REQ-022) sin el tope `_REGEX_REACH`: cada `/` de `(/[` recorre el resto de la línea | `locate_ts.py` | `test_locate_hostile_input.py::test_a_hostile_line_costs_linearly[regex_classes_never_closed]` | `growth < MAX_GROWTH`: ×308,6 (50 KB en 35 s) |
| M16 (REQ-022) secciones con la copia `found_headings[k + 1 :]` por encabezado | `locate.py` | `test_locate_hostile_input.py::test_many_headings_cost_linearly` | `assert 74.67 < 25.0` |
| M17 (REQ-022) recorrido recursivo del árbol de Python | `locate.py` | `test_locate_hostile_input.py::test_a_long_elif_chain_keeps_the_index` | `RecursionError: maximum recursion depth exceeded` |

M6 sobrevivió en la primera pasada: el test usaba `intro_heading_line`, cuyo `intro` casaba con un título del índice y el resultado salía igual con y sin el mutante. Se cambió a `heading_line` y ahora lo detecta (commit 380f9d57).

### Prueba en vivo (P6)

En proceso, desde el worktree de B, con la key del lanzador cifrado y log de uso temporal, dentro de la ventana `test-window` `w-20261123T151835Z` (12:18–12:20, hora de Uruguay), con 16,9 GB libres. El daemon no se reinició.

| Issue | Entrada sintética | Antes (issue o research §8) | Ahora |
| --- | --- | --- | --- |
| #692 | `linter_notes.md`, `tres_reglas_desactivadas` | `true` en un campo de lista | `["MD013","MD033","MD041"]`, una llamada a `gemma3-4b`, 5,3 s |
| #694 | `steps_panel.ts` de 450 líneas con JSDoc de viñetas, `orden_local_y_barra_con_lineas` | rangos de JSDoc (75-81) en vez del código | por elección del `enum` (`by: selection`), rol `code`, la función pedida con su rango exacto (más las 20 `pasoN` cuyo JSDoc habla de la barra), ningún rango de JSDoc; 60,6 s con la carga del modelo |
| #696 | `spec.md` con 22 `REQ-NNN`, `requisitos_con_lineas` | líneas equivocadas o falsos dudosos | 22/22 exactas, por programa, sin llamada |
| #697 | `big.patch` de 26 ficheros, `lista_de_ficheros_con_sus_lineas` | null (el sinónimo no se reconocía) | 26/26 rangos exactos, por programa, sin llamada |
| #698 | `big_component.ts` de 906 líneas, `funciones_con_lineas` | 3 trozos, 106 s, 20 marcadas como dudosas por error | 60/60 exactas, por programa, sin llamada |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `uv run --locked pytest -n 2` (bajo `pesado.sh`) | sí | pass | Primera pasada: 8520 pasan y 8 fallan, seis arreglados después y los dos de tiempo de 1 MB rehechos (REQ-022). Sobre f55e57ac, en el worktree con el `.venv` del checkout principal: 8599 pasan, 31 se saltan, 7 fallan; uno era el léxico (arreglado en 9dab4c2b) y seis de hooks (`test_hook_entry.py`, `test_hook_record_read_endpoint.py`, `test_read_classifier.py`) comparan la huella del CLI instalado, que en un worktree es la del checkout principal: en el checkout principal pasan, y en el CI limpio, también. Zona de locate y extract (258 tests) verde en 9dab4c2b |
| CI del PR #713 sobre 9dab4c2b | sí | pass | 22 de 22 checks en verde (ubuntu, windows y macos, lint, CodeQL, secretos). El job de macOS se canceló una vez sin llegar a tener runner (0 pasos en 15 min) y pasó al relanzarlo |
| CI del PR #713 sobre a8c2574f (rebasado sobre main con #715, con los arreglos de seguridad) | sí | pass | 22 de 22 checks en verde; hilo de CodeQL («Empty except») arreglado y resuelto; PR en estado CLEAN |
| `uv run ruff check src tests scripts` | sí | pass | sin hallazgos |
| `uv run ruff format --check src tests scripts` | sí | pass | sin cambios |

## Quality checks

- [x] Project-native tests pass (CI del PR en verde sobre a8c2574f; ver «Commands»).
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes (secrets, GitGuardian y code scanning en verde en el PR).
- [x] No unrelated changes are present.

## Deviations and residual risk

- REQ-022, tiempo de 1 MB (resuelto el 2026-11-23): con el tope absoluto de 1 s el CI fallaba en ubuntu (1,25–1,7 s de CPU). El perfil sobre 1 MB mostró dos costes evitables en `locate.py`: buscar cada ancla con un `in` por línea en Python (0,22 s con 41 anclas, y cuadrático porque las anclas crecen con la respuesta) y recorrer todos los bloques del índice por cada ancla en `_anchor_block` (0,10 s). Ahora una sola cadena con `str.find` y `bisect` por ancla, y los bloques ordenados una vez por llamada (`_BlockSpans`). Lo que queda es el lexer de TS (~0,45 s, un bucle de Python por token, ya con una sola regex para los tokens comunes). El test mide ahora la proporción 100 KB → 1 MB en CPU (`tests/linear_cost.py`), que no depende del runner. Riesgo residual: buscar las anclas sigue siendo «anclas × tamaño» (cada `find` recorre el fichero), pero en C; con 407 anclas sobre 1 MB da ×13,8 frente al tope ×25.
- Hubo que tocar tres sitios fuera del inventario para que la suite completa quedara en verde:
  - `scripts/build_corpus.py`: frontera de prompt declarada 0.54.0 para `local_extract` (el `max_tokens` y el `response_format` tipado) y `tests/test_corpus.py`. Mismo patrón que la 0.50.0 de #621.
  - `scripts/data/spanish_lexicon.json`: palabras nuevas clasificadas.
  - `scripts/data/name_exceptions.json`: el vocabulario español de `classify_field` y los nombres de campo en español de los tests, cada uno con su motivo.
- La prueba en vivo de #694 se resolvió por elección del `enum`, no por ancla: el camino del ancla con el modelo real no se ejercitó en vivo (sí en los tests, con el backend falso).
- Revisión independiente (personal-sdd-result-reviewer): 1 importante (faltaba `test_the_696_fields`) y 8 menores. Se arreglaron en df3f3b19:
  - `role_reason` en una llamada solo de programa;
  - dos avisos con texto falso;
  - la lista suelta `[5, 9]`;
  - el `located.index` que se comparaba consigo mismo;
  - la fila única del reintento;
  - fixtures de 140 KB y de 906 líneas;
  - la skill y la memoria con `located` y `type_mismatch_keys`.
- Segunda revisión independiente (personal-sdd-result-reviewer, 2026-11-23, diff desde df3f3b19^): confirma cerrados el importante y los menores de la primera, y la equivalencia exacta de `_Lines.hits` y `_BlockSpans`. Hallazgos nuevos:
  - H1 importante (REQ-004): el lexer rápido devolvía un NBSP (u otro blanco Unicode) delante de `{`, `}`, `/`, comillas o comilla invertida como palabra, porque `(\s*)` cedía un blanco a la clase de identificador; el lexer anterior lo saltaba. Arreglado con `(\s*+)` y su test (M12).
  - H2 importante (evidencia): esta verificación citaba d58cd50e y la suite en rojo. Actualizada con la corrida sobre la cabeza y el CI del PR.
  - El arreglo de `role_reason` de la primera revisión no tenía test que lo distinguiera: añadido (M13).
  - H3 menor, justificado: en el test de anclas las anclas crecen con el fichero, así que mide índice más «anclas × tamaño» en C. Es a propósito: así M10 (búsqueda por línea en Python) sale en rojo. En producción las anclas están acotadas por `max_tokens`.
  - H4 menor, aceptado: `_anchor_block` sigue recorriendo los contenedores (tablas, viñetas, bloques de código) de Markdown por ancla. Con las anclas acotadas por `max_tokens` el coste es lineal en el tamaño; queda como riesgo.
  - H5 y H6 menores: la cuenta de mutantes y el comentario de `_FILE_WORDS` en `line_check.py`, arreglados. Las líneas de más de 100 caracteres de la skill y la memoria son prosa en Markdown, fuera de ruff; se dejan.
- Revisión de seguridad (personal-security-reviewer, 2026-11-23): sin ejecución de código ni rutas; tres hallazgos de disponibilidad con un fichero hostil, todos medidos y arreglados:
  - media: el lexer de TS/JS era cuadrático en una línea de comillas que no cierran (40 KB, 13 s) o de `(/[` (40 KB, 21 s). Ahora la comilla que no cierra se recuerda hasta dónde llegó su búsqueda (exacto: toda comilla intermedia era la mitad de un escape) y la regex literal se busca hasta 512 caracteres (una más larga se lee como `/`, y en el peor caso el índice queda vacío con aviso). 1 MB de comillas: 1,5 s;
  - baja: las secciones de Markdown copiaban la lista de encabezados por cada uno (100 000 encabezados, 7,3 s); ahora una pila (0,3 s);
  - baja: una cadena de 1 200 `elif` daba `RecursionError` sin capturar en el recorrido del árbol de Python; ahora el recorrido usa su propia pila, en el mismo orden.
  - Además, CodeQL marcó un `except` vacío en `_python_comment_lines`: ahora devuelve lo leído con un comentario que dice por qué.
- Desviación anotada (REQ-001): `_local_delegate.model_error.raw` y `dropped` pueden llevar texto del modelo, números incluidos. Son diagnóstico del fallo, no valores, y se conservan a propósito.
- Desviación anotada (REQ-015): `extract_schema._NOT_PLURALS` (windows, macos, news, series…) es una lista corta de palabras acabadas en `s` que no son plurales. Resuelve `soporta_windows`, que el spec pedía `boolean` y que la regla de plural daba `list`.
