# Verification: local_extract: ficheros de un diff por programa y respuesta de líneas cortada (#665, #666)

## Environment

- Revision: rama del worktree sobre b4669c85 (main)
- Relevant runtime and tool versions: Python 3.11.15, pytest con xdist (-n 2), ruff del `.venv`

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_every_file_of_a_chunked_diff_comes_back, test_fields_that_ask_for_the_files_of_a_diff | pass | 30 ficheros con su rango exacto; con el código de main el test da 4 entradas, una por trozo (control positivo) |
| REQ-002 | test_the_diff_files_survive_an_answer_that_is_not_json, test_a_backend_error_beside_the_diff_files_is_not_silent, test_json_that_is_not_an_object_keeps_the_diff_files, test_fields_that_do_not | pass | `model_error` con `error` y `raw`; singular fuera |
| REQ-003 | test_another_location_field_over_a_diff_keeps_the_models_value, test_a_file_that_is_not_a_diff_is_left_to_the_model, test_an_inline_diff_is_left_to_the_model | pass | valor del modelo intacto |
| REQ-004 | test_a_single_call_diff_is_answered_by_program_too | pass | `_DIFF_LINES_CLAUSE` en el system |
| REQ-005 | test_a_cut_single_call_is_retried_in_halves | pass | 120 líneas recuperadas sin error; con main, una sola llamada y error |
| REQ-006 | test_a_cut_call_too_small_to_split_says_max_tokens, test_an_answer_that_is_not_json_without_a_cut_keeps_its_error | pass | `mcp.extract.not_json_cut` es y en |
| REQ-007 | test_an_answer_that_stays_cut_says_max_tokens_and_checks_its_lines, test_a_cut_chunk_beside_good_ones_has_its_lines_checked | pass | `raw: 99999` y `raw: 88888` en `lines_unverified` |
| REQ-008 | test_a_cut_answer_without_location_fields_is_not_retried | pass | una sola llamada |
| REQ-009 | test_a_retried_call_is_one_usage_row_that_reads_the_file_once, test_a_cut_call_with_only_diff_files_is_not_retried, test_a_truncated_answer_that_is_not_json_writes_a_failed_row (sin cambios) | pass | una fila, `chunks` = llamadas, ahorro una vez |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -q -n 2 (suite completa, con pesado.sh) | sí | pass | 7739 passed, 31 skipped; el único rojo (nombre `redone` del detector de nombres) se corrigió y su test pasa: 72 passed en la nueva corrida de esos dos ficheros |
| pytest tests/test_extract_diff_files_and_cut.py contra el src de main | sí | fail esperado | 17 de 21 fallan por la razón de los issues (control positivo) |
| ruff check src tests | sí | pass | All checks passed |
| ruff format --check src tests | sí | pass | 364 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La implementación se escribió justo tras reproducir los issues y antes de aprobar spec y plan;
  las puertas se aprobaron después con el diseño ya probado. Registrado aquí.
- Sin prueba contra el backend real (401 desde agentes): el prompt con la cláusula de diff y el
  rehecho se prueban con `_run_chat` doblado. Queda una prueba en vivo con `test-window`.
- `lines_unverified` con `raw:` puede marcar un número de otro campo de la respuesta cortada.
