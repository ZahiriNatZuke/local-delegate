# Verification: local_extract: el prompt pide null y prohíbe rellenar con otra clave o fila

## Environment

- Revision: rama `fix/extract-prompt-sin-relleno`.
- Relevant runtime and tool versions: `.venv` del checkout principal con `PYTHONPATH=src`; ruff del mismo `.venv`.

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_extract_no_fill.py (llamada única, numerada, map y reduce) | pass | mutante sin la cláusula hace fallar los 3 tests y los 6 de cuerpos de extract |
| REQ-002 | tests/test_corpus.py (corpus F2 y afinidad: `local_extract` aparece como frontera declarada, sin errores) | pass | suite completa |
| REQ-003 | tests/test_request_body_compat.py con `_CHANGED_SYSTEM_SUFFIX` | pass | mutante sin la cláusula hace fallar los 6 casos `extract_schema*` |
| REQ-004 | tests/test_extract_no_fill.py (tres formas de lista vacía en texto a `[]`; `"[1]"`, `"{}"`, `"none"`, `""`, `"x"` no) | pass | mutante sin decodificar hace fallar los 4 casos; sin quitar el prefijo falla el del prefijo |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| uv run --locked pytest (equivalente: `.venv` + `PYTHONPATH=src` + `-n 2`, con `pesado.sh`) | sí | pass | 6757 passed, 29 skipped (tras la revisión) |
| ruff check / ruff format --check (src tests scripts) | sí | pass | All checks passed; 370 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Tests existentes tocados con autorización del orquestador, solo donde congelan el prompt:
  `_CHANGED_SYSTEM_SUFFIX` en `test_request_body_compat.py` (precedente `_CHANGED_MAX_TOKENS`, #580)
  y `local_extract` en las dos listas de fronteras de `test_corpus.py`. Las fixtures no se
  regeneran: llevan `f2dd267` y la herramienta da diferencias en 8 de ellas.
- Datos: excepción del prompt en `tests/data/uncatalogued_exceptions.json`; `authors` y `gist` en el léxico.
- Sin medición «después» contra el backend real en esta rama: la clave del backend es un secreto
  DPAPI del usuario y no se toca; queda para la prueba conjunta (REQ-005).

## Final result

- Merged in `main` as `1a4d720d` (PR #621, 2026-11-09T17:44:22Z).
- `main` CI on `1a4d720d`: test (windows-latest) red on its own merge commit: `test_questions.py::test_the_timeout_expires_and_not_before`, unrelated and intermittent.
- Reverted by PR #624 (`c25e608f`, 2026-11-09T18:54:51Z): two regressions in the live test and the #586 case not fixed. #586 reopened.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
