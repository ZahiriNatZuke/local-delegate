# Verification: recompute-cost no pierde el relleno ni los agregados si la lectura previa falla

## Environment

- Revision: rama `fix/recompute-cost-sin-perdida` sobre `origin/main` (`ac33807a`)
- Relevant runtime and tool versions: Windows 11, Python 3.11.15, pytest + xdist `-n 2`, filelock 4.2.4

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_backfill_survives_a_transient_read_failure` | pass | en `main`: `assert 1 == 51` |
| REQ-002 | `test_backfill_is_not_written_over_an_unreadable_file`, `test_an_unreadable_old_backfill_does_not_seed_a_partial_new_one` | pass | en `main`: `DID NOT RAISE`; ahora exige `READ_ATTEMPTS` intentos |
| REQ-003 | `test_run_survives_a_transient_aggregates_read_failure`, `test_run_writes_nothing_if_the_aggregates_cannot_be_read`, `test_a_failing_stat_does_not_seed_from_the_old_aggregates` | pass | en `main`: `KeyError: '202608'`, `DID NOT RAISE`; mutante `exists()`: `KeyError: '202608'` |
| REQ-004 | `test_the_cli_says_it_could_not_read` | pass | en `main` el mensaje decía «escribir» sin nombrar el fichero |
| REQ-005 | `test_a_damaged_backfill_is_set_aside_before_being_replaced`, `test_a_damaged_aggregates_file_is_set_aside`, `test_a_backfill_with_the_wrong_shape_is_set_aside` | pass | en `main`: `TypeError on_damaged`, `assert [] == [b'{ esto no es JSON']` |
| REQ-006 | `test_a_second_run_waits_for_the_lock`, `test_the_lock_is_released_when_the_run_fails` | pass | en `main`: `DID NOT RAISE` y la CLI salía con 0 |
| REQ-007 | suite completa | pass | 6709 passed, 29 skipped; el único rojo (`test_detect_spanish_names`, por un `plazo_dias` en el test nuevo) se arregló y se repitió en verde |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` | yes | pass | 1 failed (detector de nombres, test nuevo) → corregido; recheck 102 passed |
| `ruff check` / `ruff format --check` | yes | pass | ficheros tocados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Las copias `.damaged-*` no se podan (fuera de alcance; solo aparecen con un fichero dañado).
- En POSIX el `.lock` queda en disco, como los demás cerrojos del proyecto.
