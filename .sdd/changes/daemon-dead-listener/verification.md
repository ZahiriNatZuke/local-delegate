# Verification: El daemon sale (y se puede relevar) cuando su listener HTTP muere

## Environment

- Revision: rama `fix/daemon-dead-listener` sobre `fea54181`
- Relevant runtime and tool versions: Windows 11, CPython 3.11.15, uvicorn 0.54.0, filelock

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `test_a_daemon_whose_listener_closes_exits_with_an_error_and_says_why` (daemon real en subproceso, puerto y estado temporales) | pass | sale con 3, sin `daemon.json`, lock libre; mutante sin `should_exit` → «the daemon stayed alive after losing its listener» |
| REQ-002 | `test_the_shutdown_is_bounded_and_the_listener_is_watched` | pass | mutante sin `timeout_graceful_shutdown` → `assert (None is not None)` |
| REQ-003 | `test_serve_relieves_a_registered_daemon_that_no_longer_listens` + 5 tests de la decisión (acepta, recién arrancado, pid muerto, fichero reescrito, timeout ≠ rechazo) | pass | mutante `stale = None` → «the daemon exited early: lock ocupado…»; mutante timeout→rechazo → `assert True is False`; guarda de pid reutilizado (hora de creación del proceso ≤ `started_at`): mutante `if False` → fallan `test_a_pid_reused…` y `test_a_process_whose_age_cannot_be_told…`; e2e con `skipif` fuera de Windows/Linux |
| REQ-004 | asserts sobre `daemon-errors.log` en los tests de REQ-001 y REQ-003 | pass | el log del caso Windows contiene `Accept failed on a socket` (asyncio) y `listening socket closed` (vigilante) |
| REQ-006 | `test_resets_in_the_backlog_do_not_take_the_listener_down_on_windows` + `scratchpad/i576/turn_stress.py` (40 clientes de turno con RST, 60 s) | pass | sin el envoltorio: el test ve `exit 3`, y la prueba de carga pierde el puerto en 1 s; con él: 60 s, 43 842 peticiones, puerto vivo. Mutante sin filtro de log → «never retrieved» en el log. Tras el primer CI (Windows, Python 3.11.9: proceso vivo y puerto rechazando) se cubrió el fallo síncrono de `AcceptEx` y se separó el tope (solo errores que no son reset): 3 tests unitarios portables con proactor falso; mutantes «sin captura síncrona» y «tope también para resets» → falla cada uno su test; test de resets 5/5 en verde |
| REQ-005 | `test_doctor_tells_an_alive_daemon_without_listener_from_no_daemon` + control negativo | pass | mutante `if False` → `assert 'missing' == 'warn'` |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `ruff check .` / `ruff format --check .` | sí | pass | All checks passed; 439 files already formatted |
| `pytest -q -n 2 --dist loadgroup` (suite completa, `PYTHONPATH=src`) | sí | pass | 1.ª corrida: 2 guardianes rojos (léxico y texto sin catalogar) → corregidos; 2.ª corrida: 6480 passed, 30 skipped; 3.ª (con REQ-006): 6480 passed, 30 skipped; 4.ª (tras el CI): 6482 passed, 30 skipped y 1 ajeno (`test_build_hook`: `register.js` generado por otro test en el worktree; tras borrarlo, 2 passed) |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Revisión independiente del PR #578 («mezclar con cambios»), atendida en la misma rama:
  1. `registered_process` (doctor) usa la misma guarda de pid reutilizado que el relevo; tests `test_doctor_does_not_blame_a_process_that_reused_the_pid` (mutante sin la guarda → falla) y `…_when_it_is_still_that_process`.
  2. Los errores de `accept` que no son corte de cliente se reintentan con espera creciente 0,01 s → 1 s (`_ACCEPT_BACKOFF_S`); tests `…with_a_growing_wait` (mutante `call_soon` → `[] == [0.01, 0.02, 0.04]`) y `…retried_at_once`.
  3. Riesgo residual anotado en `_refuses_connections`: en Windows una cola de `listen` llena también rechaza; un daemon vivo con el bucle bloqueado durante todo el sondeo podría ser relevado.
  4. La excepción a «nunca señal a un pid leído de un fichero» queda escrita en `update._terminate` y en el CHANGELOG.
  5. Código de salida 75 (`EX_TEMPFAIL`) en vez de 3, que en Windows se confunde con `abort()`.

- En macOS no hay relevo: la hora de creación del proceso solo se lee en Windows y Linux; el fallo de #576 es del `ProactorEventLoop` de Windows.
- El handler del logger `asyncio` hace que esos errores vayan al fichero y ya no a stderr por `lastResort` cuando el daemon corre en primer plano.
- Un daemon en su apagado ordenado (≤ 10 s, socket ya cerrado) cumple las condiciones de relevo; se pierde su limpieza, y el nuevo sobrescribe `daemon.json`.
- La rotación del log (2 × 256 KB) no tiene test propio: es la configuración de `RotatingFileHandler`.

- Nadie relanza solo el daemon tras salir con código 75: la tarea programada de Windows (la crea el
  usuario, `docs/wiki/Daemon.md`) no tiene reinicio por fallo; ahora el `Start-ScheduledTask` o un
  `serve` manual sí funcionan. launchd (`KeepAlive`) y systemd (`Restart=on-failure`) sí lo reponen.
- La causa exacta del 2026-11-04 no se pudo observar (sin logs); la reproducida (WinError 64 en
  `accept`) produce exactamente los síntomas del issue y ocurre bajo la carga descrita.

## Final result

- Merged in `main` as `d75c09cf` (PR #578) on 2026-11-04T18:21:13Z.
- PR checks (`gh pr checks 578`): 20 of 22 green (tests on ubuntu/windows/macos, Python 3.11–3.15 matrix, plugin ubuntu/windows, lint, secrets, audit, install-smoke, test-lang-es, CodeQL, Socket, GitGuardian); `plugin (macos-latest)` cancelled after 15 min and therefore `ci-gate` failed. Merged without that macOS job (bypass); the user explicitly authorized merging without macOS on 2026-11-04 (temporary bypass of the `protect-main` ruleset, restored afterwards; recorded in the day's handoff).
- `main` CI on `d75c09cf` (`gh run list --commit d75c09cf…`): CodeQL, Wiki and Vendor audit green; CI red only because `test (macos-latest)` and `plugin (macos-latest)` were cancelled (ci-gate: `[FALLO] … conclusion=cancelled`). Every other job green. `main` CI green again from `e85c0519` and on `cf1474d8`.
- Closed on 2026-11-04 by the closing PR `chore/close-sdd-2026-11-04-tarde`.
