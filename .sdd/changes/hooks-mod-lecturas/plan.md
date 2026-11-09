# Implementation plan: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Approach

- #595: `hook_common.local_tools_absent(payload)` junto a `backend_down` (no toca `record`). Los hooks
  la consultan justo despues de `backend_down()` y registran `mcp_absent` con los mismos campos.
- Prefiltro: anadir salto de linea, comilla invertida y `$(` a `READ_CHAINING` en `mod/read.js`;
  `register.js` lo regenera `build_mod.py` (no versionado).
- Cache: `test_windows` separa el fallo pasajero y `load` no lo guarda; `backend_params._read_document`
  cuenta los `OSError` pasajeros en un contador que `_resolved` compara antes y despues de `_compute`
  (no se cachea si cambio). `load` y `_read_document` conservan su forma (un test los parchea).

## Ordered tasks

<!-- One checklist item per task: "- [x] T<n> — title (REQ-NNN, ...)". Close it with [x]; drop it with
"- [-] T<n> ... dropped: <reason>". Every requirement needs at least one task that is not dropped. -->

- [x] T1 — Senal de MCP ausente y uso en los hooks de Read y shell (REQ-001, REQ-002)
  - Files or modules: resources/hooks/hook_common.py, suggest_delegate_read.py, suggest_delegate_shell.py, tests/test_hooks_mcp_absent.py
  - Verification: pytest tests/test_hooks_mcp_absent.py y tests de hooks existentes
  - Depends on: none
- [x] T2 — Prefiltro del mod con salto de linea, comilla invertida y `$(` (REQ-003)
  - Files or modules: mod/read.js, mod/read.test.ts, tests/test_read_classifier.py
  - Verification: claude plugin test; pytest tests/test_read_classifier.py
  - Depends on: none
- [x] T3 — No cachear fallos pasajeros (REQ-004)
  - Files or modules: test_windows.py, backend_params.py, tests/test_transient_read_cache.py
  - Verification: pytest de los tests nuevos y existentes de ambos modulos
  - Depends on: none
- [x] T4 — CHANGELOG y suite completa (REQ-001, REQ-002, REQ-003, REQ-004)
  - Files or modules: CHANGELOG.md
  - Verification: suite completa con pesado.sh y -n 2
  - Depends on: T1, T2, T3

## Test strategy

- Unit: los tres frentes con controles positivos (cada test nuevo falla sin el fix).
- Integration: hooks lanzados como proceso (como los instala Claude Code) con LOG simulado.

## Rollback

- Revertir el PR; sin migraciones ni formato persistente nuevo.
