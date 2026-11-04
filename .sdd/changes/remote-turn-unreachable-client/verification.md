# Verification: Turno remoto inalcanzable: en serie, corte y aviso (#577)

## Environment

- Revision: rama `fix/remote-turn-unreachable-client` sobre `fea54181`
- Relevant runtime and tool versions: CPython 3.11.15 (uv), Windows 11, pytest con xdist `-n 2`

## Evidence

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_without_turn_the_calls_go_one_at_a_time_and_all_succeed`, `test_a_cancelled_wait_for_the_blind_place_leaves_and_frees_nothing` | pass | mutante «sin serie» los tumba («2 calls ran at once…») |
| REQ-002 | `test_a_timeout_without_turn_cuts_the_calls_waiting_behind_it`, `test_a_success_without_turn_closes_the_cut`, `test_a_granted_turn_closes_the_cut`, `test_the_cut_off_keeps_the_series_but_never_cuts` | pass | mutantes «sin alimentar el corte» y «el turno concedido no cierra» los tumban |
| REQ-003 | `test_a_timeout_without_turn_cuts_the_calls_waiting_behind_it`, `test_with_the_cut_open_a_new_call_fails_at_once`; prueba en vivo con sockets reales | pass | 1 llamada al backend de 4; las otras 3 con `RemoteTurnDown` |
| REQ-004 | `test_the_error_of_a_call_without_turn_says_so`, `test_a_granted_or_local_call_has_no_note` | pass | mutante «sin nota» lo tumba |
| REQ-005 | `test_a_wait_leaves_when_another_already_found_the_daemon_unreachable` | pass | mutante lo tumba («it probed again…») |
| REQ-006 | `test_the_event_of_a_cut_call_says_why` | pass | mutante «sin evento propio» lo tumba |
| REQ-008 | `test_a_chunked_operation_gives_the_blind_place_between_chunks`, `test_a_wait_for_the_blind_place_that_does_not_move_is_saturated`; revisión: `test_a_5xx_at_once_neither_opens_the_cut_nor_says_no_turn`, `test_a_429_wait_is_not_cut_short_by_another` | pass | 5 mutantes de la revisión, cada uno tumba su test |
| REQ-007 | suite completa | pass | 6400 passed, 30 skipped; los 2 rojos se explican abajo y pasan tras arreglarlos |

## Commands

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test | `pytest -q -n 2 --dist loadgroup` | pass | 6400 passed / 2 failed / 30 skipped; luego los 2 + nuevos: 144 passed |
| lint | `ruff check src tests` | pass | All checks passed |
| format | `ruff format --check src tests` | pass | 315 files already formatted |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes. (GitGuardian en el PR)
- [x] No unrelated changes are present.

## Deviations and residual risk

- Los 2 rojos de la primera corrida: `test_detect_spanish_names` (cinco palabras inglesas nuevas sin
  clasificar: se añadieron a `scripts/data/spanish_lexicon.json`) y `test_sdist_carries_what_regenerates_the_mod`
  (el `register.js` generado por la instalación editable de `uv run` en el worktree; trampa conocida,
  no es del cambio: borrado el generado, pasa).
- La serie es por proceso; dos procesos de la misma máquina podrían ir a la vez sin turno. El corte
  sí es compartido por fichero.
- Los ~55 s de espera de turno del issue venían de respuestas `queued`/`429` seguidas de dos lecturas
  perdidas (el daemon a medio colgar, #576); eso sigue costándole a la primera tanda. Lo nuevo evita
  que se repita en las que esperan detrás y en las siguientes.

## Final result

- Merged in `main` as `576344b5` (PR #579) on 2026-11-04T18:29:54Z.
- PR checks: 22 of 22 green (`gh pr checks 579`: tests on ubuntu/windows/macos, plugin on ubuntu/windows/macos, Python 3.11–3.15 matrix, lint, audit, secrets, install-smoke, test-lang-es, ci-gate, CodeQL, Socket, GitGuardian). macOS ran and passed; no bypass.
- `main` CI on `576344b5`: green (`gh run list --commit 576344b5…`: CI, Vendor audit, Wiki, CodeQL success).
- Open after the merge: CodeQL alerts 202 and 203 (`py/catch-base-exception`, note) in `tests/test_remote_turn_unreachable.py`, and their two PR threads unresolved.
- Closed on 2026-11-04 by the closing PR `chore/close-sdd-2026-11-04-tarde`.
