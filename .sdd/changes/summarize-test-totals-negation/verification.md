# Verification: local_summarize: aviso cuando el resumen niega una categoria que el runner de tests conto

## Environment

- Revision: rama `fix/summarize-test-totals-negation` sobre `main` 05529e3c
- Relevant runtime and tool versions: Python 3.11 del `.venv` del repo con `PYTHONPATH=src`, pytest con xdist (`-n 1`), ruff del proyecto; Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_the_totals_of_each_runner_are_read` (6 casos: pytest con y sin `=`, jest, cargo, go) y `test_prose_is_not_a_totals_line` (4) | pass | recuentos de fallos y saltos exactos; la prosa sin duración no cuenta |
| REQ-002 | `test_the_summary_of_the_issue_comes_with_one_warning`, `test_the_inline_text_is_checked_too`, `test_a_denial_is_found_in_both_languages` (5), `test_a_failure_denied_while_the_runner_failed_is_flagged` | pass | un aviso con «ni saltos», la línea `750 passed, 2 skipped in 81.33s` y `local_lint_summary`; el resumen vuelve igual |
| REQ-003 | `test_a_faithful_summary_is_not_flagged` (6), `test_a_faithful_summary_comes_without_a_warning`, `test_without_a_totals_line_nothing_is_flagged` | pass | 0 avisos |
| REQ-004 | `test_the_check_is_linear_on_hostile_input` | pass | entrada de ~400 KB con `1 passed, ` repetido, `--- ` y `no ` repetidos: muy por debajo de 5 s |
| REQ-005 | pytest de 14 ficheros de la zona; control positivo con el `server.py` de `main`; ruff | pass | ver «Commands» |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pesado.sh pytest -q -n 1 tests/test_summarize_runner_totals.py | 2026-11-16 (hora de Uruguay) | pass | 31 passed |
| control positivo: mismo fichero con `git show main:src/local_delegate/server.py` | 2026-11-16 | pass | 2 failed (los dos tests de la tool, `assert 0 == 1` avisos: la razón del issue), 29 passed; luego se restauró el `server.py` con el arreglo |
| pesado.sh pytest -q -n 1 de los 13 ficheros `test_summarize_*`, `test_lossless_summary_output`, `test_structured_summary`, `test_i18n_parity`, `test_no_uncatalogued_text`, `test_detect_spanish_names`, `test_input_encoding` | 2026-11-16 12:40 (hora de Uruguay) | pass tras un arreglo | primera pasada 414 passed, 2 failed (guardianes: `Totals` y `filtered out` sin excepción; seis palabras de runner sin clasificar en el léxico); tras añadirlas, 416 passed |
| pesado.sh pytest -q -n 1 de los 7 ficheros que leen CHANGELOG, la wiki o los corpus (`test_corpus`, `test_deprecations`, `test_map_reduce`, `test_extract_table_routing_docs`…) | 2026-11-16 | pass | 927 passed |
| ruff check y ruff format --check sobre los ficheros tocados | 2026-11-16 | pass | sin avisos |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Sin la suite completa (orden de la sesión principal: 4 agentes en la máquina; solo la zona
  afectada). La correrá el CI del PR conjunto.
- Sin prueba en vivo desde el agente (backend 401): la hace la sesión principal con el caso del
  issue. El prompt no cambia, así que el riesgo de la prueba en vivo es solo de cobertura del
  detector (una negación escrita de otra forma), no de regresión.
- Límites: la negación tiene que ir antes de la palabra, en la misma frase y a menos de seis
  palabras; «los saltos no aparecen» (negación detrás) no se ve. vitest, mocha y unittest no se
  leen.
