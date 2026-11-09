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
| REQ-004 | tests/test_extract_no_fill.py (tres formas de lista vacía en texto a `[]`; `"[1]"`, `"{}"`, `"none"`, `""`, `"x"` no) | pass | mutante sin decodificar hace fallar los 3 casos |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| uv run --locked pytest (equivalente: `.venv` + `PYTHONPATH=src` + `-n 2`, con `pesado.sh`) | sí | pass | 6756 passed, 29 skipped |
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
