# Handoff: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

## Current state

- SDD status: `implementing` → `verifying` (puertas spec y plan aprobadas; quality y conformance, ver `state.json`).
- Last completed gate: plan.
- Current revision: rama `feat/codex-session-attribution` (push hecho; el PR conjunto de #684/#669/#670/#671 lo abre la sesión principal).

## What changed

- `codex_hooks.SPECS` gana `codex-mcp-call` (`PreToolUse`, matcher `^mcp__local[-_]delegate__`), al
  final; `matcher_matches` copia `HookMatcher` de Codex; el manejador vuelve a mirar el `tool_name`.
- `hook_common.record_codex_call`: nota `codex-<id>.json` (siete campos, sin `cwd`, transcript,
  entrada ni id de sesión en claro) en el directorio de notas de siempre.
- `clients`: `callId` y `sessionId` (en hash) solo de `codex-mcp-client`.
- `attribution`: `resolve_codex_call`, `is_codex_row`, `current_call`/`current_session_key` por
  cliente, `caller_column` → `codex` primero. `server._log_event` resuelve Codex también sin id.
- `transcripts.match_lines` salta Codex; `cost.merge_row` no le funde entrada; `in_flight_row` no le
  aplica atribución (recibo igual).
- Panel: `codex_calls` y columna «Codex» condicional; `measure_adoption.py` con `codex`.
- Docs: CHANGELOG, README, wiki (`Integration-install.md`, `Savings-and-metrics.md` «Delegaciones de Codex»).

## Decisions

- `_meta.sessionId` se usa (solo de Codex, en hash) como clave de sesión de la fila: en
  `rust-v0.169.0` sale de `sess.session_id()`, igual que el `session_id` del hook
  (`core/src/mcp_tool_call.rs:630-635`, `core/src/hook_runtime.rs:206-219`). Sin hook aprobado la
  fila tiene sesión. `threadId` no se lee.
- El modelo de Codex va en `caller_model` tal cual (validado por patrón); las filas de Codex ya están
  fuera del coste, y el recibo en curso de Codex no lo toma (no hay precio de Claude que aplicarle).
- `caller_column` da `codex` antes que `mod`: una fila de Codex nunca es del mod.
- Los tests del núcleo que fijaban «dos hooks» pasan a leer `SPECS`, para que #670 y #671 añadan
  entradas sin romperlos. La entrada nueva va al final: el índice es parte de la clave de aprobación.

## Next action

1. **Capturas del panel (claro y oscuro)**: la sesión principal las lanza con la máquina tranquila
   (`scripts/dev/capture_dashboard.py`, que ya trae `codex_calls: 31` en la fila de Codex). Hay que
   ver la columna «Codex» en «Quién delegó» y que «Sin dato» solo queda en la fila `unknown`.
2. **Prueba con Codex real (la hace la persona usuaria; no se simula):**
   1. Instalar la rama con `uv tool` (parar el daemon, `uv tool install --force --no-cache
      <checkout>`, arrancarlo) y `local-delegate install --clients codex`.
   2. En Codex, `/hooks`: aparece `codex-mcp-call` pendiente (los dos de antes siguen aprobados si
      ya lo estaban); aprobarlo.
   3. Pedir a Codex una delegación en el hilo principal («resume README.md con local_summarize»),
      otra desde un subagente y, si se usa code mode, una desde código.
   4. En el log de uso del día (`usage-AAAAMM.jsonl` del `LOG_DIR`), las líneas `client:
      codex-mcp-client` deben llevar `tool_use_id` (el de code mode empieza por `exec-`),
      `caller_session_key`, `caller_src: codex-hook`, `caller_model` (el modelo de Codex),
      `caller_kind` `main`/`subagent` y, en el subagente, `caller_agent_type`. Si falta
      `tool_use_id` o `caller_session_key`, el SDK MCP no entrega `_meta.callId`/`sessionId` como se
      supuso: es un fallo. Si hay `tool_use_id` pero no `caller_src`, el hook no despachó o su
      `tool_name` no casa el matcher (mirar `codex-hooks-seen.json` y el `tool_name` real).
   5. Panel: «Quién delegó» muestra la columna «Codex» con esas llamadas. Las líneas de las tres
      delegaciones de la misma sesión de Codex comparten `caller_session_key` (también la del
      subagente): eso confirma que `_meta.sessionId` y el `session_id` del hook coinciden. Con el
      `session_id` en claro (el que Codex pasa a sus hooks), `/api/stats?session=<ese id>` devuelve
      solo esas.
   6. `local-delegate doctor`: «aprobados en /hooks: 3 de 3».
   7. Vuelta atrás: `local-delegate uninstall --clients codex --no-mcp --no-memory --no-skill`.

## Memory

- Canonical note: sin nota aparte; lo durable va en este handoff (Decisions), `review.md` y el CHANGELOG; la jornada del vault la escribe la sesión principal.
- Indexes updated: no
