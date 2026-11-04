# Verification: local_explain_code sobre un diff troceado: índice completo y líneas del patch (#582)

## Environment

- Revision: rama `fix/explain-chunked-diff-index` desde `origin/main` d75c09cf
- Relevant runtime and tool versions: Python del `.venv` del repo, `PYTHONPATH=src` (worktree)

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests `test_the_ranges_of_a_git_diff_*`, `test_a_diff_without_git_headers_*`, `test_deleted_renamed_and_added_*`, `test_what_is_not_a_diff_*` | pass | tests/test_explain_code_diff_index.py |
| REQ-002 | tests `test_each_chunk_is_told_its_files_*`, `test_the_map_asks_one_bullet_per_file_*` | pass | con el server.py de main falla el assert de la pista y el de «CADA fichero» |
| REQ-003 | tests `test_the_system_says_hunk_header_numbers_*`, `test_a_small_diff_is_one_call_*` | pass | cláusula y `_DIFF_NOTE` en todos los system (map, reduce, llamada única) |
| REQ-004 | test `test_the_issue_case_ends_with_every_file_and_its_real_lines` | pass | con main la respuesta es la del modelo (5 ficheros) y falla el assert de la cabecera del índice |
| REQ-005 | tests `test_a_chunked_answer_says_it_was_chunked_*`, `test_chunked_code_with_a_question_*`, `test_inline_diff_*`, `test_a_plain_chunked_explanation_keeps_its_output` | pass | con main falla el assert del aviso |
| REQ-006 | `test_without_a_question_the_prompts_are_unchanged` (hash de prompts y salida) y tests de explain/map-reduce | pass | 375 passed en los ficheros afectados, ninguno modificado |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest ficheros afectados (`-n 2`, 19 ficheros de explain, map/reduce, idioma, i18n, smoke) | sí | pass | 375 passed; la suite completa no se corrió en local (2,8 GB de RAM libre < 6 GB): la corre el CI |
| control positivo | sí | pass | con el `server.py` de `origin/main` fallan 8 de los 13 tests nuevos; pasan los 4 de `line_check` (función nueva) y el guardián de «sin cambios» |
| ruff check / ruff format | sí | pass | sin hallazgos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- REQ-005 se restringió: la explicación troceada sin pregunta ni diff no lleva el aviso, porque su
  salida está congelada por hash en un test existente que no se toca.
- No se responde sin modelo cuando la pregunta es solo un índice: detectarlo pide heurística de
  idioma; el índice exacto va siempre al final.
- La «línea correcta marcada como dudosa» del issue no se reprodujo: citas correctas en cuatro
  formatos (`ruta (líneas a-b)`, `ruta: a–b`…) no dan aviso sobre el diff sintético.
- Sin prueba en vivo: el daemon corre la 0.48.0 instalada, no esta rama.
