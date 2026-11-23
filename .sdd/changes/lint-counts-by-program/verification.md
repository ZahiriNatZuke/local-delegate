# Verification: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

## Environment

- Revision: rama `fix/lint-counts-by-program` sobre `3bba8117` (v0.54.0), worktree propio, `PYTHONPATH=src`.
- Relevant runtime and tool versions: Python 3.11, pytest con xdist (`-n 2`, bajo `pesado.sh`), ruff; Windows 11.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test_the_smoke_case_gets_the_line_of_the_program_and_the_warning, test_many_files_are_listed_up_to_ten_and_the_rest_counted, test_the_line_in_english | pass | rojos antes (11 de 13 del fichero), verdes después; en vivo la línea sale en ruff y tsc |
| REQ-002 | test_the_smoke_case_names_the_foreign_code_and_the_wrong_total, test_a_wrong_figure_for_a_code_inside_and_outside_the_entries, test_tsc_and_ruff_full_are_checked_too, test_a_total_word_followed_by_a_code_is_the_figure_of_that_code | pass | el caso del humo nombra el F401 de core.py y el total de util.py |
| REQ-003 | test_right_figures_among_line_numbers_give_no_mismatch, test_a_right_summary_gets_the_line_and_no_warning, test_what_the_program_cannot_tell_gives_no_warning, test_a_bold_line_under_heading_entries_is_not_part_of_the_last_one | pass | con controles que sí avisan; en vivo 4 resúmenes correctos sin aviso |
| REQ-004 | test_formats_without_per_file_counts_stay_as_they_were (eslint, pytest) | pass | en vivo eslint sale como antes |
| REQ-005 | test_the_long_role_gets_them_too, test_the_chunked_summary_gets_them_too | pass | el troceado comprueba que hubo más de una llamada |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` (con `pesado.sh`) | 2026-11-23 | pass | 8659 pasados, 31 saltados; dos tests de llama-swap que fallaron una vez bajo carga pasan solos y en las corridas siguientes |
| `ruff check src tests` y `ruff format --check` | 2026-11-23 | pass | sin hallazgos |
| `pytest -q -n 2` (con `pesado.sh`), PR #722 rebasado sobre main | 2026-11-23 | pass | 8722 pasados, 32 saltados; ruff limpio |
| prueba en vivo en proceso (`test-window` `w-20261123T184924Z`, label `lint-0-54-1`) | 2026-11-23 | pass | antes/después con ruff, tsc y eslint, 2 corridas cada uno |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- En vivo el modelo acertó las cifras: el fallo del humo no se reprodujo, así que el aviso se verifica con backend simulado; en vivo se verifica la línea y la ausencia de avisos falsos.
- R6 y R7 arreglados en el PR #722 (suite completa en verde con `pesado.sh -n 2`, 8686 pasados antes de los arreglos de su revisión; ver la fila de la corrida final).
