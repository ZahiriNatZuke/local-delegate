# Implementation plan: local_lint_summary: recuentos por fichero y por código por programa, con aviso si el resumen da otra cifra (#717)

## Approach

- `lint_patterns.py`: `count_mismatches(answer, per_file)` recorre el resumen por entradas
  (`_entry_file`, como el chequeo de fallos de pytest del #641; `_same_file` para nombres base),
  lee el total de la entrada (`N errores|avisos|…`) y la cifra pegada a cada código (`E501: 2`,
  `E501 (2)`, `E501 ×2`, `2× E501`), y devuelve las discrepancias con la cifra del log. Las
  líneas fuera de entradas solo se comparan por código.
- `server.py`: `_lint_counts(log, answer, text)` añade la línea del programa y el aviso; se encadena
  tras `_test_figures` en las tres `postprocess` de `local_lint_summary`, como el #715.
- i18n es/en: `mcp.lint_counts.line`, `mcp.lint_counts.more`, `mcp.warning.summary_lint_counts`.

## Ordered tasks

- [x] T1 — Tests rojos: caso del humo, resumen correcto, tsc, ruff completo, eslint y pytest sin cambio, troceado (REQ-001, REQ-002, REQ-003, REQ-004, REQ-005)
  - Files or modules: tests/test_lint_counts_by_program.py
  - Verification: fallan sin el arreglo
  - Depends on: none
- [x] T2 — `lint_patterns.count_mismatches` (REQ-002, REQ-003)
  - Files or modules: src/local_delegate/lint_patterns.py
  - Verification: tests de T1
  - Depends on: T1
- [x] T3 — `_lint_counts` en las tres `postprocess` e i18n (REQ-001, REQ-004, REQ-005)
  - Files or modules: src/local_delegate/server.py, resources/i18n/{es,en}/mcp.json
  - Verification: tests de T1 y suite completa
  - Depends on: T2

## Test strategy

- Unit: `count_mismatches` sobre resúmenes sintéticos que distinguen cifra buena y mala.
- Integration: `local_lint_summary(text=…)` con backend falso, roles `mechanical` y `long` y troceado.
- End-to-end or manual: prueba en vivo en proceso dentro de `test-window` (`lint-0-54-1`).
- Security and secret scanning: `personal-security-check` antes del commit.

## Migration and compatibility

- Solo añade texto al final de la respuesta para formatos reconocidos; los demás no cambian.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
