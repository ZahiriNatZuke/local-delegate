# Verification: Las escrituras concurrentes a la telemetria no pierden ni corrompen lineas

## Environment

- Revision: rama `fix/telemetria-escritura-concurrente` sobre `origin/main` (`ac33807a`)
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, pytest + xdist `-n 2`; CI: ubuntu, windows, macos

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_concurrent_records_keep_every_line` (6 × 400) ×3 | pass | en `main`: `assert 2105 == 2400` |
| REQ-002 | `test_concurrent_threads_keep_every_line` (8 × 200) | pass | en `main`: `assert 1578 == 1600` |
| REQ-003 | `test_concurrent_blocks_keep_every_note` + `tests/test_correlation.py` | pass | en `main`: `assert 3 == 96` |
| REQ-004 | `test_concurrent_failures_keep_every_line` | pass | en `main`: `assert 328 == 360` |
| REQ-005 | `test_racing_mod_roads_write_one_line` (8 × 150) | pass | en `main` pasaba (la comprobación previa casi basta); mutante `unless=None`: 2 de 3 corridas fallan (152 y 161 frente a 150) |
| REQ-006 | `test_a_torn_last_line_does_not_swallow_the_next` | pass | en `main`: `assert [None] == [None, 1]` |
| REQ-007 | `test_readers_skip_a_non_object_line` | pass | en `main`: `assert False` (filas no-dict) |
| REQ-008 | `test_a_held_lock_does_not_hang_the_hook` | pass | en `main`: no existía `_try_lock` |
| REQ-009 | suite completa local + matriz de CI del PR | pass | 6706 passed, 30 skipped; el único rojo (detector de nombres: `racing`, `readers`, `roads`, `torn`, `unlock`) se arregló en el léxico y se repitió en verde (46 passed) |

Repro de la tarjeta con el arreglo (6 × 300): `valid=1800 corrupt=0` tres veces (antes 1515/1593/1616).

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` | yes | pass | ver REQ-009 |
| `ruff check` / `ruff format --check` | yes | pass | ficheros tocados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- En POSIX los tests concurrentes no discriminan (el `write` con `O_APPEND` ya era atómico): son de no regresión.
- `mod/read.js` `readRecordLost` sigue reescribiendo `hook-failures.jsonl` (fuera de alcance; seguimiento).
- Un hook que escribe nota y línea puede esperar hasta ~2 s si otro retiene el cerrojo (acotado).
