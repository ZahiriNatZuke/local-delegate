# Verification: Codex: guard de escritura y lecturas, huecos de la revisión (#706, #707)

## Environment

- Revision: rama `fix/codex-guard-fixes` sobre `main` en `f0e060c9`, worktree propio con su `.venv`
  (`uv sync --frozen --all-extras`), `PYTHONPATH=src`.
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, pytest con xdist `-n 2`.

## Evidence

Antes del arreglo, los tests nuevos se corrieron sobre el código de `main`: 27 rojos, cada uno por la
razón que dice (p. ej. el `apply_patch` seguía denegado tras la lectura con el interruptor apagado).

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | CPU de `_PATCH_PATH` con 40 000 espacios; CRLF y espacios finales; ruta vacía | pass | `test_the_patch_paths_come_out_in_linear_time` (rojo antes: ~5 s de CPU), `test_a_patch_path_loses_its_trailing_blanks_and_the_cr` |
| REQ-002 | Lectura literal con interruptor por variable, inactivo, fichero y backend caído; tramos que suman; otro agente; escritura en el mismo comando | pass | `test_a_literal_read_lifts_the_guard_with_the_switch_off` (8 casos), `test_ranges_read_with_the_switch_off_still_count`, `test_the_switch_off_does_not_lift_another_agents_guard`, `test_a_write_in_the_same_command_does_not_hide_the_read`, `test_backend_down_lets_it_through_and_the_literal_read_lifts_the_guard` |
| REQ-003 | Varios ficheros y tuberías que no eligen líneas pasan con nota; filtro de franja sigue denegando; búsqueda no levanta | pass | `test_a_read_with_more_files_or_a_pipe_passes_with_the_note` (4), `test_a_pipe_into_a_range_filter_is_still_the_read`, `test_a_search_does_not_lift_the_guard` |
| REQ-004 | `Select-Object -Skip/-First/-Last/-Index` en el clasificador y en la cobertura de Codex | pass | `test_select_object_skip_moves_the_range` (8), `test_select_object_skip_counts_its_own_lines`; fila 338 del corpus ajustada en `_expected` con su motivo |
| REQ-005 | Dos tramos con `;`, `&&` y salto de línea llegan al 80 %; control al 79 %; compuesto mixto cuenta para la siguiente; dos ficheros no es solo lectura | pass | `test_the_ranges_of_one_compound_command_add_up` (3), `test_ranges_of_one_command_under_the_share_pass`, `test_ranges_in_a_mixed_compound_command_count_for_the_next_read`, `test_reads_of_two_files_in_one_command_are_not_only_the_read` |
| REQ-006 | Daemon que tarda 0,4 s por petición con plazo de 1 s da `None`; con 5 s, el resumen | pass | `test_the_summary_deadline_is_for_the_whole_call`, `test_the_same_slow_daemon_answers_within_a_longer_deadline` |
| REQ-007 | Lectura MCP con guard puesto: nota y el guard sigue | pass | `test_a_mcp_read_never_lifts_the_guard`; wiki `Integration-install.md`, fila de lectura MCP |
| REQ-008 | 31 días se borra, 29 se queda, `.txt` se queda; fallo al borrar no cambia nada | pass | `test_old_session_logs_are_pruned_when_a_session_starts`, `test_a_prune_that_cannot_delete_leaves_the_read_alone` |
| REQ-009 | `Get-Content -TotalCount`, `Set-Content`, `Out-File`, `mv`, `Move-Item`, tubería, varios ficheros, varias líneas | pass | `test_get_content_total_count_is_a_range_that_counts`, `test_more_shell_writes_on_a_summarized_file_are_refused` (6, con control sin guard), y los de REQ-003/REQ-005 |
| REQ-010 | Cabecera con espacios/tab; una tubería que acaba en `head > out` o en `Out-File` no levanta; 20 000 `\"` en < 1 s y la escritura detrás se ve | pass | `test_a_patch_header_with_blanks_before_it_is_still_guarded`, `test_a_read_that_goes_to_a_file_does_not_lift_the_guard` (2), `test_escaped_quotes_outside_quotes_tokenize_in_linear_time`, `test_a_read_whose_output_goes_to_a_file_is_marked` (3); rojos sobre el código anterior (6 fallos, el troceado tardaba minutos) |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` (suite completa, con `pesado.sh`) | yes | pass | 8340 passed, 32 skipped |
| `ruff check src tests scripts` | yes | pass | All checks passed |
| `ruff format --check src tests scripts` | yes | pass | 429 files already formatted |
| `scripts/bump_version.py --boundaries` | yes | pass | `hook_hashes_after.json` con la huella nueva de `read_classifier.py` |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Dos tests existentes cambian de forma explícita: el de backend caído fijaba el fallo de #707 y se
  invierte; el de comando compuesto cambia de nombre porque un compuesto de solo lecturas del mismo
  fichero ahora sí se resume.
- De `cat a.md b.md` solo cuenta el primer fichero (límite del clasificador, anotado en la spec).
- La prueba con Codex real sigue pendiente del SDD `codex-read-summary-write-guard`.
