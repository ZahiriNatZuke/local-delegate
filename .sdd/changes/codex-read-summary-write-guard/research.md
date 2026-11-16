# Research: Codex: resumen automático de lecturas y guard de escritura (#670)

Fuente: `openai/codex`, etiqueta `rust-v0.169.0` (clon parcial en el scratchpad; rutas relativas a
`codex-rs/`). Codex CLI instalado: 0.169.0. Lo de Codex se leyó en el código; lo «medido» se
comprobó con un `CODEX_HOME` temporal (`scripts/dev/codex_hooks_live.py`, `hooks/list`).

## Current behavior

- `codex_hooks.SPECS` tiene `codex-prompt` (`UserPromptSubmit`) y `codex-subagent-start`
  (`SubagentStart`); `codex_hooks.run` despacha por nombre. Ningún hook sobre herramientas.
- El mod de Claude (`resources/claude-plugin/local-delegate/mod/read.js`, `readOnToolCall`,
  líneas 1086-1196) hace: guard de escritura (`readGuardRefusal`), clasificación con
  `hook classify` (`hook_entry.classify_text` → `read_classifier.classify`), resumen automático de
  prosa grande entera (`readSteer`), cobertura acumulada por rangos con umbral 0,8
  (`READ_WHOLE_SHARE`, `readCoverage`, `readLiteralBudget`), fichero corto que pasa (`readShortFile`:
  ≤200 líneas y <32 KB), rangos literales en subagente sin contar para el principal, y validez del
  resumen (`readSummarize`: vacío, `[local-delegate error]`, aviso de «moved to the background»).
- `read_classifier.classify` ya acepta la entrada de Codex: `{tool_name: "Bash", tool_input:
  {command}, cwd}` (`accesses`: `SHELL_TOOLS` o nombre vacío con `command`); con nombre vacío admite
  también los verbos solo de PowerShell, que es el shell de Codex en Windows.

## Hechos de Codex 0.169.0 (citados)

- **PreToolUse puede denegar con un motivo que ve el modelo.** Salida
  `hookSpecificOutput.permissionDecision: "deny"` + `permissionDecisionReason`
  (`hooks/schema/generated/pre-tool-use.command.output.schema.json`; `hooks/src/events/pre_tool_use.rs`,
  test `permission_decision_deny_blocks_processing`). `core/src/hook_runtime.rs`
  (`run_pre_tool_use_hooks`): para `Bash` y `apply_patch` el modelo recibe
  `"Command blocked by PreToolUse hook: {reason}. Command: {command}"`; para otra tool
  `"Tool call blocked by PreToolUse hook: {reason}. Tool: {name}"`. `core/src/tools/registry.rs`
  (`apply_pre_tool_use`): con `Blocked` la herramienta **no se ejecuta**. Es la vía de sustitución:
  el resumen va en el motivo y el original nunca se lee.
- **`additionalContext` sin denegar** se acepta en `PreToolUse` (`pre_tool_use.rs`, rama de
  `append_additional_context` antes de mirar `block_reason`): sirve para avisos.
- **`updatedInput`** solo con `permissionDecision: "allow"` (test
  `permission_decision_allow_can_update_input`); `allow` sin él y `ask` fallan en abierto. Reescribir
  el comando a un `echo` del resumen se descarta: pasa por sandbox y aprobación del shell, y en
  Windows por el quoting de PowerShell; el motivo de `deny` no.
- **PostToolUse no puede sustituir la salida de Bash:** `updatedMCPToolOutput` es «unsupported» y
  falla en abierto (`post_tool_use.rs`, test `unsupported_updated_mcp_tool_output_fails_open`).
  `decision: "block"` sí cambia lo que ve el modelo (`registry.rs`: `RespondToModel(message)`), pero
  la lectura ya se ejecutó; además la respuesta de Bash solo llega si el proceso terminó
  (`context.rs`, `post_tool_use_response` devuelve `None` con `process_id`). Por eso no hace falta
  PostToolUse: todo va en PreToolUse.
- **Entradas.** Shell (`exec_command`): `tool_name: "Bash"`, `tool_input: {"command": cmd}`
  (`handlers/unified_exec/exec_command.rs`, `pre_tool_use_payload`); `cwd` es el `workdir` de la
  llamada si es local (`pre_tool_use_cwd`). `apply_patch`: `tool_input: {"command": <parche
  freeform>}` (`handlers/apply_patch.rs`), con líneas `*** Add File:`, `*** Update File:`,
  `*** Delete File:` y `*** Move to:`. MCP: `mcp__<namespace>__<tool>` con sus argumentos.
  Subagente: `agent_id` = id del hilo del subagente, `agent_type` = rol
  (`hook_runtime.rs`, `subagent_hook_context`); el principal no los lleva.
- **Matcher** (`hooks/src/engine/matcher.rs`): solo `[A-Za-z0-9_|]` = lista exacta; si no, regex sin
  anclar (`regex` de Rust). `apply_patch` también casa con `Write`/`Edit` (`hook_names.rs`).
- **Timeout** (`hooks/src/engine/discovery.rs`, `normalize_command_hook`): el del manejador, sin
  tope salvo `SessionEnd`/`Interrupt`; por defecto 600 s. Pasado el plazo el hook es `Failed` y el
  turno sigue (fallo en abierto).
- **Código de salida:** 2 bloquea; cualquier otro no cero = `Failed`, no bloquea. `local_delegate.hook`
  nunca sale con 2.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `codex_hooks.py` | SPECS, entradas, fusión, despacho | una entrada más en SPECS (con matcher y `timeout` propio), etiqueta `pre_tool_use`, una rama en `run` | `codex_hooks.py:100-107`, `:404-428` |
| `codex_reads.py` (nuevo) | — | decisión del hook, estado por sesión, cliente del `/mcp` del daemon | — |
| `resources/hooks/hook_common.py` | catálogo de textos de hooks | claves `codex.read.*`/`codex.guard.*` es/en | `hook_common.py:1601` |
| `attribution.py` | clientes fuera del coste | el cliente del hook (`local-delegate-codex-read`) como `not_claude` | `attribution.py:43` |
| tests `test_codex_hooks*.py` | contrato de #669 (dos hooks) | el recuento pasa a tres; aserciones de los dos consultivos sin cambio | `tests/test_codex_hooks.py:106-118`, `test_codex_hooks_install.py:40` |
| `docs/wiki/Integration-install.md` | «Hooks de Codex» | hook nuevo, conclusión técnica y límites | `:483-500` |

## Existing conventions

- Fallo en abierto en todo; textos ASCII en `HOOK_TEXTS` con paridad es/en (`test_i18n_parity.py`).
- Escritura concurrente: `hook_common.append_line` (cerrojo de fichero, una escritura).
- Rutas: `read_classifier.resolve`; claves del mod con `readNormalize` (minúsculas en Windows).

## Dependencies and integrations

- Sin dependencias nuevas: `urllib` de la stdlib para el `/mcp` del daemon; `desktop_bridge.daemon_url`
  y `token_source.web_token` para la URL y el token (los mismos que el puente de Desktop).

## Risks and unknowns

- Confirmado en código, no en vivo: que el modelo de Codex usa el resumen del motivo y no reintenta
  la lectura por otra vía. Va a la prueba en vivo con centinela.
- Supuesto: `session_id` puede ser compartido entre principal y subagentes; el estado se separa por
  `agent_id`, así que no importa.
- La lectura literal levanta el guard al permitirla (antes de ejecutarse): si el comando falla, el
  guard ya se levantó. Riesgo residual aceptado: el fichero existe (se midió su tamaño).
