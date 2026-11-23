# Verification: Resumen de salidas de tests: totales y versión por programa, y aviso de negación sin falsos positivos

## Environment

- Revision: rama `fix/test-summary-figures-by-program` sobre `main` `d46f3c5a`.
- Relevant runtime and tool versions: Python 3.11 del `.venv` del checkout principal con
  `PYTHONPATH=src` del worktree; pytest con xdist (`-n 2`) bajo `pesado.sh`.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_test_summary_figures.py::test_a_comma_ends_the_negation | pass | rojo en main (avisaba `skips`), verde con el cambio; control positivo sin coma sigue avisando |
| REQ-002 | tests/test_test_summary_figures.py::test_a_figure_in_words_ends_the_negation | pass | rojo en main; controles «las omitidas» y «ni un salto» siguen avisando |
| REQ-003 | tests/test_test_summary_figures.py::test_errors_are_their_own_category | pass | rojo en main (`failures` por «sin errores»); «sin fallos» sobre `1 error` sigue avisando |
| REQ-004 | tests/test_test_summary_figures.py::test_the_warning_cites_the_line_that_counts | pass | rojo en main (citaba `3 passed in 2.00s`) |
| REQ-005 | tests/test_test_summary_figures.py::test_summarize_adds_the_program_line y test_lint_summary_* (mecánico, largo, troceado) | pass | rojos en main; la línea no se añade si la respuesta ya cita los totales literales (test_an_answer_quoting_the_totals_gets_no_line) |
| REQ-006 | tests/test_test_summary_figures.py::test_another_python_version_is_flagged | pass | rojo en main; la misma versión y `Python 3.11` no avisan |
| REQ-007 | cmd pesado.sh pytest -n 2 (suite completa) | pass | 8438 pasan; 6 de hooks (`test_hook_entry`, `test_hook_record_read_endpoint`, `test_read_classifier`) fallan igual con el cambio guardado en `git stash`: entorno del worktree; 2 de `test_lint_pytest_failures` se arreglaron sin tocarlos (la línea no se añade si la respuesta cita los totales) |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -n 2 -q (pesado.sh, PYTHONPATH=src) | sí | pass | ver REQ-007 |
| ruff check / ruff format --check | sí | pass | ficheros tocados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La prueba en vivo depende de tener 8 GB libres; ver la sección de prueba en vivo del PR.
- No se comparan los recuentos de la prosa con los del runner (decisión del spec).
