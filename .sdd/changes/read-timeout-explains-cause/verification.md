# Verification: Un read_timeout dice si fue cola, carga o generación y en qué trozo (#572)

## Environment

- Revision: rama `fix/commit-msg-timeout-cause` sobre `origin/main` 81f84356
- Relevant runtime and tool versions: Python del `.venv` del repo, `PYTHONPATH=src` (worktree), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test tests/test_read_timeout_explains.py (trozo 1 de un commit troceado, trozo 2 de un resumen, reducción, trozo 2 de una traducción, sin trozos) | pass | 10 passed; control positivo sin el arreglo: KeyError `pieces`/`read_timeout_piece` |
| REQ-002 | test tests/test_read_timeout_explains.py (modelo `starting` y luego `ready` durante el envío; listo desde la primera muestra; campo en el evento) | pass | control positivo: AttributeError/KeyError `read_timeout_load_ms` |
| REQ-003 | test tests/test_read_timeout_explains.py (turno de 2,4 s nombrado; 0,4 s no) | pass | control positivo: el texto acababa en el de «ocupado» |
| REQ-004 | test tests/test_read_timeout_cause.py intacto, más los negativos nuevos | pass | 9 passed sin tocar el fichero; `HTTP_TIMEOUT` sin cambios |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -q -n 2 (suite completa, con `pesado.sh` y logs temporales) | sí | pass | 6475 passed, 30 skipped |
| ruff check src tests | sí | pass | All checks passed |
| ruff format --check (ficheros tocados) | sí | pass | formateados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La carga se mide con la resolución de la vigilancia (10 s): «listo a los ~S s» es aproximado.
- Lo que hace esperar dentro de llama-swap a otra máquina (la Mac va directa al backend) sigue sin
  verse desde este daemon; el texto no lo afirma.
- Sin prueba en vivo con el backend real (necesita un plazo agotado de verdad); queda para la sesión
  principal si la quiere.
