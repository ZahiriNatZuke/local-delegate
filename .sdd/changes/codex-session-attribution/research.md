# Research: Atribución de cada delegación de Codex a su sesión (#669, segunda parte)

Parte de `.sdd/changes/codex-native-hooks/` (cerrado, PR #682): su `research.md` («Hechos de Codex
0.169.0») y su `handoff.md` («Next action», punto 2). Fuente de Codex: `openai/codex`, etiqueta
`rust-v0.169.0` (`d32063f9`), clon parcial en el scratchpad; rutas relativas a `codex-rs/`.

## Current behavior

- Una delegación pedida por Codex llega con `clientInfo.name == "codex-mcp-client"` y se registra
  con `client: codex-mcp-client`, sin `tool_use_id` ni `caller_*`: `clients._tool_use_id_from` solo
  lee `_meta["claudecode/toolUseId"]` (`src/local_delegate/clients.py:186-194`) y
  `server._log_event` solo llama a `attribution.current_call()` si hay id (`server.py:1499-1505`).
- `attribution.resolve_call` solo resuelve notas `toolu_…` (`TOOL_USE_ID_PATTERN`,
  `resources/hooks/hook_common.py:2273`) con transcript de Claude bajo `~/.claude/projects`.
- Coste: `attribution.exclusion_reason` ya aparta `codex-mcp-client` como `not_claude`
  (`attribution.py:43`, `:556-562`); lo usan `cost.segment` (`cost.py:275`), `recompute`
  (`recompute.py:183`) y `valuation` (`valuation.py:205`). Las filas de Codex cuentan como uso.
- Relleno a posteriori: `transcripts.match_lines` (`transcripts.py:408-451`) trata TODA fila sin
  `caller_model`; una de Codex sin `tool_use_id` puede cruzarse por ventana (`window`) con un
  `tool_use` de Claude de la misma tool y el mismo segundo, y `cost.merge_row` (`cost.py:182-205`)
  le funde ese `caller_model`/`caller_kind` ajeno. Es atribución falsa (Claude a una llamada de
  Codex).
- Panel: `attribution.caller_column` (`attribution.py:541-553`) da `mod`/`main`/`subagent`/
  `unknown`; `web/metrics.py:258-265` (`_CALLER_FIELDS`) y la tarjeta «Quién delegó»
  (`metrics.py:2594-2630`). Las filas de Codex caen en `unknown_caller_calls`.
- Resumen por sesión: `/api/stats?session=<id>` filtra por `caller_session_key ==
  hook_common.session_key(id)` (`metrics.py:716-719`, `:758-761`); `/api/inflight` usa
  `caller_session_key` de la entrada en curso (`server.py:458-462`, `attribution.current_session_key`).
  Las filas de Codex no traen clave y no entran en ningún resumen por sesión.
- `scripts/measure_adoption.py:60,242,301` cuenta `delegations_by_caller` con las columnas
  `main/subagent/mod/unknown`; `scripts/measure_plugin_adoption.py` solo mira Claude Code
  (`exclusion` → `other_client`).

## Hechos de Codex 0.169.0 (citados)

- `_meta` de cada `tools/call` MCP: `callId` = el `call_id` de la invocación
  (`core/src/mcp_tool_call.rs:1447-1457`, `build_mcp_tool_call_request_meta`), `threadId` =
  `sess.thread_id` y `sessionId` = `sess.session_id()` (`mcp_tool_call.rs:630-635`, `:1557-1576`,
  `with_mcp_tool_call_ids_meta`).
- `PreToolUse`: `session_id: sess.session_id()` (`core/src/hook_runtime.rs:206-219`,
  `run_pre_tool_use_hooks`), `tool_use_id` = el mismo `call_id`, `model` = slug del modelo del paso,
  `agent_id`/`agent_type` solo en un subagente `ThreadSpawn` (`hook_runtime.rs:1086-1105`:
  `agent_id` = `thread_id` del subagente, `agent_type` = su rol o el rol por defecto). **Conclusión:
  `_meta.sessionId` y el `session_id` del hook salen de la misma función de la misma sesión**: son
  el mismo valor para una misma llamada. No trae esfuerzo.
- Esquema de entrada de `PreToolUse` (`hooks/schema/generated/pre-tool-use.command.input.schema.json`):
  requeridos `cwd`, `hook_event_name`, `model`, `permission_mode`, `session_id`, `tool_input`,
  `tool_name`, `tool_use_id`, `transcript_path` (string o null), `turn_id`;
  `additionalProperties: false`. La salida vacía con código 0 es «continuar».
- Nombre de herramienta MCP en hooks: `mcp__<namespace>__<tool>` (`core/src/tools/handlers/mcp.rs:496-505`
  y test `mcp_pre_tool_use_payload_uses_prefixed_tool_name_and_raw_args`, `:673-711`); shell =
  `Bash`, `apply_patch` = `apply_patch` (research del núcleo). Matcher (`hooks/src/engine/matcher.rs`):
  vacío o `*` = todo; solo `[A-Za-z0-9_|]` = exacto (alternativas con `|`); si no, regex sin anclar.
- Code mode: las llamadas anidadas usan `call_id = "exec-<uuid v4>"`
  (`core/src/tools/code_mode/delegate.rs:323`, test `delegate_tests.rs:191-194`) y disparan
  `PreToolUse` por el despacho normal (research del núcleo).

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `codex_hooks.py` | dos hooks consultivos, fusión, `doctor` | tercera entrada `codex-mcp-call` (`PreToolUse`, matcher), `EVENT_LABELS` con `pre_tool_use`, manejador que deja la nota, comprobación del matcher | `SPECS`, `run` |
| `hook_common.py` (recurso) | nota `toolu_…` de Claude | nota de Codex con prefijo `codex-` y patrón de id propio | `record_call` |
| `clients.py` | lee `claudecode/toolUseId` | `callId` y `sessionId` (en hash) solo de `codex-mcp-client` | `_tool_use_id_from`, `observe_client` |
| `attribution.py` | resuelve la nota de Claude | resuelve la de Codex; `caller_column` con `codex`; regla `is_codex_row` | `current_call`, `current_session_key`, `caller_column` |
| `server.py` | `current_call` solo con id | `current_call` siempre (con sesión de Codex sin id) | `_log_event` |
| `transcripts.py`, `cost.py` | relleno y fusión de toda fila | filas de Codex fuera del relleno y sin fundir entrada vieja; recibo en curso igual | `match_lines`, `merge_row`, `in_flight_row` |
| `web/metrics.py` + i18n | columnas de quién delegó | `codex_calls` y columna «Codex» (solo si hay) | `_CALLER_FIELDS`, `renderClients` |
| `scripts/measure_adoption.py` | `delegations_by_caller` | columna `codex` | `CALLER_COLUMNS` |
| docs | wiki, CHANGELOG | campos nuevos y su origen | `Savings-and-metrics.md`, `Integration-install.md` |

## Existing conventions

- La sesión solo viaja como clave de un solo sentido (`hook_common.session_key`), nunca el id.
- La nota vive en el temporal del usuario, una por fichero, escrita con `os.replace`; el id se valida
  antes de construir la ruta. Su formato vive en el hook y en `attribution`, atados por un test de
  ida y vuelta.
- Una regla, un sitio: `caller_column`, `exclusion_reason`, `is_mod_call` en `attribution`.
- Observar nunca rompe una tool (`try/except` propios en el middleware y en `_log_event`).
- Los hooks salen con 0; un fallo deja una línea en `hook-failures.jsonl` con el tipo.
- Código en inglés; textos es/en por catálogo; el panel es un dashboard (sin prosa).

## Dependencies and integrations

- Sin dependencias nuevas. `jsonschema` ya está en los tests. Codex CLI es externo.

## Risks and unknowns

- Supuesto: que el SDK MCP de Python entregue `_meta.callId`/`_meta.sessionId` en `ctx.meta` como
  entrega `claudecode/toolUseId` (medido para Claude). Solo lo prueba Codex real (prueba del usuario).
- Supuesto: el namespace del servidor en el nombre del hook (`local-delegate` o `local_delegate`);
  el matcher acepta los dos.
- Riesgo: añadir `PreToolUse` deja `doctor` en `warn` («falta codex-mcp-call») a quien instaló la
  versión con dos hooks hasta `update`; y Codex pide aprobar el nuevo en `/hooks`. Los dos de antes
  conservan índice y aprobación (otra clave de evento).
- Riesgo de integración: #670 y #671 añaden entradas a `SPECS` en paralelo; la nuestra va al final.
