# Verification: Ruido del CI arreglado de raíz: gate, tests de coste, E/S real, huellas y CodeQL

## Environment

- Revision: rama `ci/root-cause-noise` sobre `0c6fc456` (main con #729)
- Relevant runtime and tool versions: Python 3.11.15, uv 0.10.12, pytest-xdist 3.8.0, Windows 11 (PC de desarrollo); el CI del PR en Ubuntu 26.04, Windows y macOS

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_ci_gate.py sin y con el cambio de `ci_gate.py` | pass | sin el cambio: 5 failed, 36 passed (los casos nuevos); con él: 41 passed; controles con runner, con paso ejecutado y `timed_out` en BAD |
| REQ-002 | tests/test_ci_gate.py (reparto de pasos, job `perf`, reintento) | pass | 63 passed con test_completion_ci_shells; `-m "not perf and not real_io"` en `test` y `test-lang-es`, paso `real_io` con `shell: bash`, job `perf` en EXPECTED_JOBS |
| REQ-003 | tests/test_perf_helper.py | pass | coste lineal pasa, cuadrático falla; control positivo real: la regex vieja de `_PATCH_PATH` da 98x contra techo 31,6x |
| REQ-004 | tests/test_timing_marker_guard.py + `pytest -m perf` en serie | pass | 73 passed en 47 s; `tests/linear_cost.py` borrado; guardián verde |
| REQ-005 | tests/test_timing_marker_guard.py | pass | antes de migrar: 3 failed (lista de tests sin marcador, `process_time` en 8 ficheros); después: 16 passed |
| REQ-006 | `pytest -m real_io` en serie | pass | 109 passed en 160 s (Windows local) |
| REQ-007 | tests/test_completion_shell_startup.py | pass | 7 passed; pwsh que aborta salta con versión, guarda avisa; ausente sigue fallando |
| REQ-008 | tests/test_check_local.py; `python scripts/check_local.py` sobre el árbol | pass | 15 passed; el script cazó 17 palabras sin clasificar del propio cambio antes del CI |
| REQ-009 | tests/test_ci_gate.py (reintento del navegador) | pass | peor caso 240 s < 300 s del paso |
| REQ-010 | tests/test_check_main.py; `python scripts/check_main.py` real | pass | 7 passed; contra GitHub: `main` (0c6fc456) en verde, 19 checks, ninguna alerta abierta |
| REQ-011 | revisión de CHANGELOG.md | pass | entrada en `[Unreleased]` / Cambiado |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest (paralelo) | `pytest -q -n 2 --dist loadgroup -m "not perf and not real_io"` con `pesado.sh` | pass | 8753 passed, 32 skipped en 6 min 21 s |
| pytest perf | `pytest -q -m perf` en serie | pass | 73 passed |
| pytest real_io | `pytest -q -m real_io` en serie | pass | 109 passed |
| lint | `ruff check .` | pass | All checks passed |
| format | `ruff format --check .` | pass | 538 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `release.py` no regenera: lo hace `bump_version.py X` (razón en `plan.md`, Approach); `release.py` se niega a publicar con huellas o capturas viejas.
- `bump_version.py X` ahora exige Playwright para la captura; `--no-capture` lo salta a sabiendas.
- El job `test` sube a 20 min (firma 25:00) por el paso en serie; `test-lang-es` a 33 y el plazo del gate a 40.
- La prueba en CI (3 corridas verdes en los tres sistemas) va en el PR.
