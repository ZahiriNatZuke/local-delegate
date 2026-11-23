# Implementation plan: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

## Approach

El mismo camino que la atribución de Claude (nota del hook por id de llamada + lectura en el
middleware), con piezas propias para que nada de Claude cambie:

1. **Hook** `codex-mcp-call` (`PreToolUse`, matcher `^mcp__local[-_]delegate__`), añadido al final
   de `codex_hooks.SPECS`. El manejador comprueba él mismo el `tool_name` con el matcher (si el
   usuario lo cambia a mano, no anota llamadas ajenas), y llama a `hook_common.record_codex_call`, que
   escribe `codex-<id>.json` en el directorio de notas de siempre (lo poda el mismo `_prune_notes`).
   No imprime nada: `PreToolUse` sin salida y con 0 es «continuar».
2. **Middleware** (`clients.observe_client`): con cliente `codex-mcp-client`, el id sale de
   `_meta.callId` y la sesión de `_meta.sessionId`, guardada ya en hash en una `ContextVar` propia.
3. **Atribución** (`attribution`): `is_codex_row`/`CODEX_CLIENT` como regla única;
   `resolve_codex_call(call_id, session_key)` y `current_call`/`current_session_key` que eligen el
   camino por cliente. `caller_column` → `codex` antes que `mod`.
4. **Servidor**: `_log_event` llama a `current_call()` también sin id (Claude sin id ya daba `{}`).
5. **Relleno y coste**: `transcripts.match_lines` salta las filas de Codex; `cost.merge_row` no les
   funde entrada; `cost.in_flight_row` no les aplica la atribución (recibo igual que antes). El coste
   ya las aparta (`not_claude`): solo se ata con un test.
6. **Panel**: `_CALLER_FIELDS["codex"] = "codex_calls"`, columna «Codex» condicional como «Sin
   dato», `panel.clients.col.codex` es/en; `capture_dashboard.py` con `codex_calls` en sus datos.
7. **Medidor**: `codex` en `CALLER_COLUMNS` de `measure_adoption.py` y en su texto «por hilo».

## Ordered tasks

- [x] T1 — Entrada `codex-mcp-call`, `EVENT_LABELS`, `matcher_matches`, manejador y nota de Codex (REQ-001, REQ-002, REQ-003)
  - Files or modules: `src/local_delegate/codex_hooks.py`, `src/local_delegate/resources/hooks/hook_common.py`, `tests/fixtures/codex_hooks/*` (esquemas `pre-tool-use` y seis payloads), `tests/test_codex_attribution.py`; tests del núcleo que fijaban «dos hooks» pasan a leer `SPECS`
  - Verification: `pytest tests/test_codex_attribution.py tests/test_codex_hooks*.py -n 1`
  - Depends on: none
- [x] T2 — `callId`/`sessionId` solo de Codex en el middleware (REQ-004)
  - Files or modules: `src/local_delegate/clients.py`
  - Verification: tests de REQ-004 y `tests/test_clients*.py`
  - Depends on: none
- [x] T3 — Resolución de Codex, `current_call`/`current_session_key` por cliente, `caller_column`, `_log_event` (REQ-005, REQ-008)
  - Files or modules: `src/local_delegate/attribution.py`, `src/local_delegate/server.py` (`_log_event`, 3 líneas)
  - Verification: tests de REQ-005 con `LOCAL_DELEGATE_LOG` temporal; `tests/test_attribution*.py`
  - Depends on: T1, T2
- [x] T4 — Fuera del relleno y de la fusión; recibo en curso igual (REQ-006, REQ-007)
  - Files or modules: `src/local_delegate/transcripts.py`, `src/local_delegate/cost.py`
  - Verification: tests de REQ-006/007 con control `claude-code`; `tests/test_transcripts*.py`, `tests/test_cost*.py`
  - Depends on: T3
- [x] T5 — Columna «Codex» y resumen por sesión (REQ-008, REQ-009)
  - Files or modules: `src/local_delegate/web/metrics.py`, `resources/i18n/{es,en}/panel.json`, `scripts/dev/capture_dashboard.py`
  - Verification: tests de REQ-008/009; `tests/test_metrics*.py`, `tests/test_dashboard*.py`; capturas claro/oscuro (las lanza la sesión principal)
  - Depends on: T3
- [x] T6 — Medidor de adopción (REQ-010)
  - Files or modules: `scripts/measure_adoption.py`, `resources/i18n/{es,en}/cli.json`
  - Verification: test de REQ-010; `tests/test_measure_adoption*.py`
  - Depends on: T3
- [x] T7 — Documentación y prueba en vivo descrita (REQ-011, REQ-012)
  - Files or modules: `CHANGELOG.md`, `docs/wiki/Savings-and-metrics.md`, `docs/wiki/Integration-install.md`, `handoff.md`
  - Verification: `tests/test_wiki.py`, `tests/test_i18n_parity.py`
  - Depends on: T1–T6

## Test strategy

- Unit: matcher, nota, middleware con `ctx` falso, resolución con notas en `tmp_path`, `caller_column`,
  `match_lines`, `merge_row`, `segment`, `_aggregate`, medidor.
- Integration: el hook lanzado como subproceso con `-I` (como lo lanza Codex) sobre los fixtures;
  `_log_event` con `LOCAL_DELEGATE_LOG` temporal; `/api/stats` y `/api/inflight` con `TestClient`.
- Controles: cada test nuevo con su caso que falla sin el cambio (cliente Claude frente a Codex,
  patrón sin ancla, nota de otro id); mutantes manuales de `is_codex_row` y del filtro del relleno.
- End-to-end or manual: Codex real (REQ-012), lo hace la persona usuaria.
- Security and secret scanning: revisión del diff (ids en claro, rutas en la nota), `personal-security-check` antes del commit.

## Migration and compatibility

- Sin migración. Una instalación con dos hooks: `doctor` avisa (`warn`, falta `codex-mcp-call`) y
  `update` lo añade al final de `PreToolUse` (o en el primer hueco); los dos de antes conservan
  índice y aprobación. Codex pide aprobar el nuevo.
- Filas viejas de Codex: pasan de «Sin dato» a «Codex»; las entradas de relleno viejas que tuvieran
  dejan de fundirse (eran cruces falsos con Claude).
- Vuelta atrás: `uninstall --clients codex` quita los tres; revertir el PR devuelve el resto.

## Plan review

- [x] Every requirement maps to at least one task and verification step.
- [x] Risky or destructive operations have safeguards and rollback.
- [x] Dependencies and configuration changes are explicit.
- [x] The plan does not include unrelated work.
