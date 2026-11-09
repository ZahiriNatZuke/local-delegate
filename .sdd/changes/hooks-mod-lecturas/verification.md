# Verification: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Environment

- Revision: rama `fix/hooks-mod-lecturas` sobre `origin/main` ac33807a.
- Relevant runtime and tool versions: Python 3.11 (`.venv` propio del worktree, `uv sync --locked
  --all-extras`, `-I` importa el worktree), Claude Code 2.1.319 para `claude plugin test`, Windows 11.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | tests/test_hooks_mcp_absent.py (hooks como proceso, entrega settings y plugin `-I -m local_delegate.hook`) | pass | Sin el fix fallan los 8 casos `absent`/subagente con `assert 'deny' is None` / `assert 'context' is None`; con el fix pasan |
| REQ-002 | tests/test_hooks_mcp_absent.py (casos `present`, funcion caso a caso) | pass | Controles `present` bloquean/avisan igual que HEAD; dudas (sin delta, pendiente, tool_use, tope, agent_id raro) dan False |
| REQ-003 | mod/read.test.ts via `claude plugin test` y tests/test_read_classifier.py::test_mod_prefilter_does_not_drop_a_hidden_read | pass | plugin test 155 pass / 0 fail; con `read.js` de HEAD 154 pass / 1 fail; el test Python falla los 5 casos con `assert None` (regex de HEAD) |
| REQ-004 | tests/test_transient_read_cache.py (simulado y cerrojo real `CreateFileW` share=0) | pass | Sin el fix: `assert [] == ['w-20261023T100000Z']` y `assert {} == {'top_k': 20}`; los controles de fallo permanente pasan en ambos |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| test (`pytest -q -n 2`, suite completa con pesado.sh) | si | fail (4, ninguno de comportamiento) | 6646 passed, 30 skipped, 4 failed: 2 de `test_hook_boundaries` (falta `bump_version.py --boundaries`, que por orden del encargo hace la release), 1 de `test_install_english` (la palabra «lecturas» sale del nombre de la carpeta del worktree), 1 de `test_detect_spanish_names` (nombres de test, corregido y verificado con el detector) |
| tests afectados (936) | si | pass | 936 passed |
| `ruff check` / `ruff format --check` de los ficheros tocados | si | pass | All checks passed |
| `scripts/build_mod.py` + `claude plugin test` | si | pass | 155 pass, 0 fail |

## Quality checks

- [x] Project-native tests pass.
- [x] Lint, formatting, type checking, and build checks pass where applicable.
- [x] Secret scanning passes.
- [x] No unrelated changes are present.

## Deviations and residual risk

- La senal de #595 sale de un formato interno de Claude Code (`deferred_tools_delta`); si cambia, el
  hook vuelve a avisar como antes (falso negativo, nunca bloquea de mas).
- Si el usuario fija TODAS las tools con `pinned_tools`, ninguna sale como diferida y, hasta el primer
  uso de una, el hook callaria con el MCP presente. Con la lista por defecto (4 de 11) no pasa.
- El mod de lectura no recibe `transcript_path`: con el MCP ausente su `$.mcp.call` falla y deja pasar.
- El panel no tiene etiqueta para `mcp_absent` (tampoco para `backend_down`); sale el valor crudo.
- Cambian `suggest_delegate_read.py`, `suggest_delegate_shell.py` y `hook_common.py`: la release debe
  regenerar `scripts/data/hook_hashes_after.json` con `bump_version.py --boundaries`.
- `tests/test_read_classifier.py` no se puede correr solo (ImportError de `path_rules`) tambien en
  main: depende de que otro test meta la carpeta de hooks en `sys.path`. Preexistente; no se toco.

## Final result

- Merged in `main` as `26a14cb9` (PR #603, 2026-11-09T13:42:22Z).
- `main` CI on `26a14cb9`: all check runs green.
- `main` at `c25e608f`: CI (run 42678307325 Wiki, 42678307752 CI), CodeQL and Vendor audit green on `c25e608f`.
- Closed on 2026-11-09 in the 0.50.0 release PR (`release/0.50.0`).
