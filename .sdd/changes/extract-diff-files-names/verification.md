# Verification: local_extract: nombres de campo de ficheros y hunks de un diff por programa, sin null silencioso (#665)

## Environment

- Revision: rama `fix/extract-diff-files-names` sobre 05529e3c (main)
- Relevant runtime and tool versions: Python 3.11.15, pytest con xdist (-n 1), ruff del `.venv`

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_files_and_hunks_of_a_92_kb_patch_come_back_by_program, test_fields_that_ask_for_the_files_and_their_hunks, test_fields_that_do_not_ask_for_files_and_hunks, test_a_file_without_hunks_gets_its_range_alone | pass | 14 ficheros con su rango y el de cada hunk, sin `warning`; con main, `null` |
| REQ-002 | test_changed_files_with_lines_over_a_chunked_diff, test_changed_files_is_not_a_count_of_lines, test_counts_stay_counts | pass | `changed_files_with_lines` por programa; `lines_changed`, `changed_lines`, `changed_files_count` siguen siendo recuentos |
| REQ-003 | test_a_patch_with_a_preamble_is_still_read_as_a_diff, test_a_preamble_in_a_file_that_is_not_a_patch_is_not_read_as_one, test_files_of_a_6000_line_format_patch_come_back_by_program | pass | `.patch` con preámbulo leído como diff; un `.md` con preámbulo no |
| REQ-004 | test_a_patch_without_file_headers_says_so | pass | `mcp.warning.extract_diff_unparsed` en `warning` |
| REQ-005 | test_a_null_location_field_over_a_chunked_diff_names_the_program_fields | pass | `mcp.warning.extract_diff_null_hint` tras el aviso de trozos |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest tests/test_extract_diff_files_names.py contra el src de main | sí | fail esperado | 15 de 22 fallan (control positivo); el de 6000 líneas con `format-patch` ya pasaba en main |
| pytest -n 1 sobre 24 ficheros vecinos (extract, explain diff, chunking, nombres, i18n, wiki, corpus, map_reduce) con pesado.sh | sí | pass | 1060 passed; tras el último ajuste (fichero sin hunks), 175 passed en los 5 ficheros más cercanos |
| ruff check src tests | sí | pass | All checks passed |
| ruff format --check src tests | sí | pass | 375 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- No se corrió la suite entera (orden del encargo: solo ficheros afectados y su vecindad); la
  corre el CI del PR que integra la sesión principal.
- Sin prueba contra el backend real desde el agente: queda la prueba en vivo de la sesión principal.
- Los informes no salen en el log de esta PC (la única llamada de hoy sobre un `.patch` es otra);
  se reproducen por su forma.
