# Verification: La espera ciega sin turno cuenta en la explicación del plazo agotado (#575 + #579)

## Environment

- Revision: rama `fix/timeout-counts-blind-wait` sobre `main` 58e37d54
- Relevant runtime and tool versions: Python del `.venv` del repo, `PYTHONPATH=src` (worktree; `local_delegate.__file__` apunta al worktree), Windows 11

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | test tests/test_read_timeout_counts_blind_wait.py (dos `local_classify` sin turno por el `_post_chat` real; `_remote_wait` con `Unusable`; cada fase interna sola, 1,6 s con nota y 0,4 s sin ella) | pass | 6 passed; control positivo: sin la fase `blind` o con la explicación sumando solo `turn`/`slot` falla `the read-timeout text does not name the blind wait`; con `_remote_wait` registrando `turn` fallan `assert "turn" not in phases` y `phase_ms('turn_unusable') >= 40` |
| REQ-002 | test tests/test_read_timeout_counts_blind_wait.py (fases del evento literales, sin `turn`; `turn_wait_ms`) y suite completa sin tocar tests existentes | pass | mutante que publica `blind` en `PHASES`: falla `set(phases) <= {"turn", "slot", "backend"}`; suite 6619 passed (los 2 fallos de `test_corpus` son previos, ver abajo) |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| pytest -n 2 -q (suite completa, con `pesado.sh` y logs temporales) | sí | pass | 6619 passed, 30 skipped, 2 failed previos (`test_corpus::test_affinity_check_is_ok_with_any_environment_language`, fallan igual con el árbol de `main` sin el cambio) |
| pytest -n 2 de los ficheros de read_timeout y remote_turn tras los ajustes de la revisión | sí | pass | 42 passed |
| ruff check src tests | sí | pass | All checks passed |
| ruff format --check (ficheros tocados) | sí | pass | 3 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- `test_corpus::test_affinity_check_is_ok_with_any_environment_language` falla en local (también sin
  este cambio: «cases.json ya no coincide con el constructor»); en CI se salta por checkout
  superficial y el CI de `main` está en verde. Fuera de alcance.
- Sin prueba en vivo con un backend real (necesita un plazo agotado de verdad).

## Final result

- Merged in `main` as `8509e7da` (PR #590, 2026-11-04T22:26:51Z).
- PR checks: 22 of 22 green (`gh pr checks 590`).
- `main` CI on `8509e7da`: CI (run 41925350983), CodeQL and Vendor audit green.
- Closed on 2026-11-04 in the 0.49.0 release PR (`chore/release-0.49.0-b`).
