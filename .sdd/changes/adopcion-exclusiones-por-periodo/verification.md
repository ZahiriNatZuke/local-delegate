# Verification: La medicion de adopcion del plugin acota las exclusiones a su periodo

## Environment

- Revision: rama `fix/adopcion-exclusiones-por-periodo` sobre `origin/main` (`ac33807a`)
- Relevant runtime and tool versions: Windows 11, Python 3.11.15 (`.venv` del checkout principal con `PYTHONPATH=src`), pytest con xdist `-n 2`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_excluded_rows_bounded_to_the_period` antes y después del arreglo | pass | En `main` falla en `assert m["excluded_rows"] == {"plugin": 1}` con `{'plugin': 3}`; con el arreglo pasa |
| REQ-002 | guarda `with_delegation == 1` y mutante que acota también los ids | pass | El mutante falla en la guarda con `assert 0 == 1`; con el arreglo pasa |
| REQ-003 | `pytest tests/test_measure_plugin_adoption.py` y suite completa | pass | 7 passed; suite completa: ver Commands |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` (suite completa) | yes | pass | 6699 passed, 29 skipped en 373 s (Windows local) |
| `ruff check` / `ruff format --check` (hooks pre-commit) | yes | pass | pre-commit del commit `d4bf0b66` |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- El test se escribió justo después del brief/spec/plan y antes de aprobar las puertas en el CLI; el arreglo, después de ver fallar el test.
- No hay test para filas sin `ts` (comportamiento sin cambios: se saltan en las dos pasadas).
