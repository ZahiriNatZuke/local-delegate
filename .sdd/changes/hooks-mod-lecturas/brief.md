# Brief: Hooks, mod y caché: lecturas sin MCP, prefiltro multilínea y fallo pasajero

## Problem

1. #595: los hooks PreToolUse de `Read` (y el de shell, que bloquea igual) sugieren o exigen tools
   `local_*` aunque el MCP `local-delegate` no esta cargado en la sesion.
2. El prefiltro JS del mod (`mod/read.js`, `READ_CHAINING`) da por inofensivo un comando de varias
   lineas o con `$(`/comilla invertida que empieza por `cd`/`ls`/`echo`, y no lo clasifica; el hook de
   shell se aparta (`read_mod_active`) y la lectura entera entra sin control.
3. `test_windows.load` y `backend_params._resolved` guardan en cache un `OSError` pasajero (cerrojo de
   antivirus) hasta que cambia el fichero.

## Desired outcome

1. Con evidencia positiva de que las `local_*` no estan en la sesion, los hooks de lectura y shell
   ni sugieren ni bloquean y registran el motivo `mcp_absent`; ante cualquier duda, como hoy.
2. Esos comandos llegan al clasificador.
3. Un `OSError` distinto de `FileNotFoundError` no se cachea; la siguiente llamada reintenta.

## In scope

- `resources/hooks/hook_common.py` (funcion nueva, lejos de la escritura de telemetria),
  `suggest_delegate_read.py`, `suggest_delegate_shell.py`.
- `mod/read.js` (`READ_CHAINING`).
- `test_windows.py`, `backend_params.py`.
- Tests nuevos y CHANGELOG.

## Out of scope

- El mod de lectura con el MCP ausente (no recibe `transcript_path`; su `$.mcp.call` falla y deja
  pasar). El hook de prompt y el de `SubagentStart` (texto ya condicional).
- Etiqueta del panel para `mcp_absent` (tampoco la tienen `backend_down` ni `protected_path`).
- La escritura de telemetria (`record`), que hoy cambia otro agente.

## Constraints and risks

- Senal de #595: el transcript (formato interno de Claude Code). Lleva adjuntos
  `deferred_tools_delta` con `addedNames`/`removedNames`/`pendingMcpServers` (medido en esta sesion y
  en sus subagentes; `scripts/_claude_bench.py:179` ya los usa). La entrada de un hook de subagente
  trae el `transcript_path` del principal; el suyo es `<sesion>/subagents/agent-<agent_id>.jsonl`
  (`attribution.py:113-128`, medido). Las tools fijadas por el mod no salen como diferidas: si se
  fijan TODAS, el hook se callaria aunque esten (limite documentado); por eso cuenta tambien un
  `tool_use` de una `local_*`.
- Coste: lectura binaria del transcript con tope de tamano; por encima del tope, como hoy.
- Falso negativo antes que falso positivo: sin transcript, sin delta o con el servidor pendiente,
  se sugiere como hoy.

## Open questions

- Ninguna que cambie la spec.

## Log

<!-- L1 is the original request, verbatim. Redact secrets and personal data (for example an e-mail
address becomes <email redacted>) before recording. Add one short entry per session: where the work
stopped and what remains. -->

- L1 2026-11-09 Original request, verbatim:

  > Issue #595 (hooks PreToolUse de Read sugieren local_* sin el MCP cargado); tarjeta prefiltro del mod (comando de varias líneas o con $( pasa sin mirar); tarjeta caché de fallo de lectura pasajero (test_windows y backend_params).
