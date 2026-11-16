# Implementation plan: Codex: resumen automático de lecturas y guard de escritura (#670)

## Approach

Un módulo nuevo `codex_reads.py` con la decisión pura `decide(payload, environ, summarize)` y sus
piezas (parche, cobertura, estado, cliente del daemon), para no reescribir `codex_hooks.py`: allí
solo una entrada en `SPECS`, el campo `timeout` de `HookSpec` (por defecto 30, así los hooks de
#669 no cambian), la etiqueta `pre_tool_use` y una rama en `run`. El clasificador es el compartido
(`hook_entry.classify_text`), con el nombre de tool vacío en Windows (PowerShell). La sustitución va
en el motivo de `deny` (único camino de Codex que impide la ejecución y muestra texto al modelo).

## Ordered tasks

- [x] T1 — Entrada en SPECS, matcher, timeout por hook y etiqueta (REQ-001, REQ-010)
  - Files or modules: `src/local_delegate/codex_hooks.py`, `src/local_delegate/codex_reads.py`
  - Verification: tests de entradas/matcher; `scripts/dev/codex_hooks_live.py`
  - Depends on: none
- [x] T2 — Decisión de lectura: resumen, cobertura, ficheros cortos, subagente, MCP (REQ-002, REQ-003, REQ-004, REQ-005, REQ-007)
  - Files or modules: `src/local_delegate/codex_reads.py`, `resources/hooks/hook_common.py` (textos)
  - Verification: `tests/test_codex_reads.py` con fixtures de entrada oficiales
  - Depends on: T1
- [x] T3 — Guard de escritura y estado por sesión/agente (REQ-006, REQ-009)
  - Files or modules: `src/local_delegate/codex_reads.py`
  - Verification: `tests/test_codex_reads.py` (apply_patch, shell, alcance, otro proceso)
  - Depends on: T2
- [x] T4 — Cliente del `/mcp` del daemon y exclusión del coste (REQ-008)
  - Files or modules: `src/local_delegate/codex_reads.py`, `src/local_delegate/attribution.py`
  - Verification: servidor HTTP falso en el test (JSON y SSE, 401, isError)
  - Depends on: T2
- [x] T5 — Wiki, CHANGELOG, prueba en vivo (REQ-011)
  - Files or modules: `docs/wiki/Integration-install.md`, `CHANGELOG.md`, `handoff.md`
  - Verification: revisión
  - Depends on: T1-T4

## Test strategy

- Unit: `decide` con un `summarize` inyectado y `LOCAL_DELEGATE_LOG_DIR` temporal; controles
  negativos (resumen inválido, entrada sin campo, matcher equivocado) que fallan sin el cambio.
- Integration: el hook por subproceso (`-I -m local_delegate.hook codex-tool-guard`) para guard,
  paso literal y entrada rota; nunca llega al daemon real ni lee el token del registro.
- End-to-end or manual: `codex_hooks_live.py` (`hooks/list`); prueba en vivo con centinela para la persona usuaria.
- Security and secret scanning: sin contenido en el estado; `git diff` revisado antes del commit.

## Migration and compatibility

- Un hook nuevo pide aprobación en `/hooks`; los dos de #669 no cambian de comando ni de hash.
- Tests de #669 que fijaban «dos hooks» pasan a contar tres, con las mismas aserciones sobre los dos.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
