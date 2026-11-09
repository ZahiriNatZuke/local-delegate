# Verification: El mod usa la histéresis del panel para el estado del backend

## Environment

- Revision: rama `fix/mod-histeresis-backend` sobre `origin/main` 7d972fc8.
- Relevant runtime and tool versions: Python 3.11 (`.venv` del worktree), Claude Code 2.1.319 para
  `claude plugin test`, node para los tests del panel, Windows 11.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | mod/status.test.ts (tests #612) | pass | con el `status.js` de HEAD fallan 3 de los 4 nuevos (un fallo suelto pinta caído) |
| REQ-002 | mod/status.test.ts `one failed probe after a good one…` | pass | tras el primer fallo, el siguiente sondeo llega a 1 s; confirmada la caida, 30 s (con el mutante `failures > 0` el test falla) |
| REQ-003 | tests/test_backend_view_shared.py | pass | con un `statusShownBackend` que devuelve el cuerpo crudo falla `assert 'down' == 'ready'` |
| REQ-004 | mod/status.test.ts `no answer from /api/backend…` | pass | la respuesta nula ni suma fallo ni pone la cuenta a cero; ese latido dice «sin datos» |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest -q -n 2` (suite completa, pesado.sh) | si | pass | 6642 passed, 30 skipped |
| `build_mod.py` + `claude plugin test` | si | pass | 158 pass, 0 fail, tambien con el test reforzado |
| `ruff check` / `ruff format --check` | si | pass | ficheros tocados |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- Se tocaron 5 tests existentes del mod (6 lineas, todas `await $.session.measure(...)` con el
  comentario «issue #612»): esperaban CAIDO tras UN solo sondeo fallido, justo lo que el issue
  declara malo. Solo se les da el segundo sondeo; las expectativas no cambian.
- Diferencia deliberada con el panel: si el daemon no contesta `/api/backend`, la banda dice «sin
  datos» ese latido (como antes); el panel repinta lo anterior. La cuenta de fallos no cambia en
  ninguno de los dos.
- El panel lee `mod/common.js` al importar; si faltara en la instalacion, `web.metrics` no importa.
  La rueda lleva todo `src/local_delegate` y el sdist lo comprueba `test_build_hook.py`.
- No toca hooks: `hook_hashes_after.json` no cambia.
