# Research: Entrega Codex nativa: hooks de usuario, instalador, diagnóstico y atribución por sesión (#669)

Fuente de Codex: `openai/codex`, etiqueta `rust-v0.169.0`, clon parcial en el scratchpad (las rutas
de abajo son relativas a `codex-rs/`). Codex CLI instalado: 0.169.0 (npm, Windows). Lo que dice
«medido» se observó con un `CODEX_HOME` temporal y el app-server (`hooks/list`).

## Current behavior

- `install` solo entrega hooks cuando el destino incluye Claude (`install.py`, `plan_install`:
  `if "hooks" in opts.components and "claude" in opts.targets`). A Codex le da la entrada MCP
  (`upsert_codex_mcp` en `~/.codex/config.toml`) y el bloque de `AGENTS.md`. Nada más.
- `doctor` tiene `codex.plugin` (#668): detecta el plugin de Claude importado en Codex; no mira
  hooks de usuario de Codex.
- Atribución por llamada: el servidor lee `_meta["claudecode/toolUseId"]` (`clients._tool_use_id_from`)
  y busca la nota que deja el hook `record_call.py` (`hook_common.record_call`), que solo acepta ids
  `toolu_…` (`TOOL_USE_ID_PATTERN`). Codex no manda esa clave: sus líneas del log llevan
  `client: codex-mcp-client` y ningún `caller_*`. `attribution.NON_CLAUDE_CLIENTS` ya las aparta del
  coste (`not_claude`), pero cuentan como uso.

## Hechos de Codex 0.169.0 (citados)

- Hooks de usuario: `hooks/src/engine/discovery.rs` (`discover_handlers`) lee, por capa de config,
  `<carpeta de la capa>/hooks.json` (`load_hooks_json`) y la tabla `[hooks]` de `config.toml`. La
  capa de usuario es `CODEX_HOME` (`config/src/state.rs`, `hooks_config_folder`). Con las dos no
  vacías avisa «loading hooks from both … prefer a single representation».
- Formato: `HooksFile` (`config/src/hook_config.rs`) con `deny_unknown_fields`: solo `description`
  y `hooks`. Mismas reglas que valida `codex_plugin.check_hooks_file` (#668).
- Confianza: cada manejador tiene clave `"{ruta}:{evento}:{grupo}:{manejador}"` (`hooks/src/lib.rs`,
  `hook_key`; etiquetas `pre_tool_use`, `user_prompt_submit`, `subagent_start`…) y un hash de su
  identidad normalizada (evento, matcher, manejador: `hook_hash`). Solo corren los `Trusted` o
  gestionados (`discovery.rs`, `if enabled && (… Trusted)`). La aprobación vive en
  `[hooks.state."<clave>"] trusted_hash` de `config.toml` (`HookStateToml`), que escribe Codex al
  aprobar en `/hooks`. Consecuencia de diseño: **la clave depende de la posición** del grupo y el
  hash del comando, así que un reinstall debe dejar nuestros grupos en el mismo índice y el mismo
  comando para no pedir aprobación otra vez.
- Matcher: `hooks/src/engine/matcher.rs`: vacío o `*` = todo; solo `[A-Za-z0-9_|]` = exacto; si no,
  regex sin anclar (`is_match`).
- Ejecución: `hooks/src/engine/command_runner.rs` (`build_command`): Windows `cmd.exe /C "<comando>"`
  (con `raw_arg` entre comillas), Unix `$SHELL -lc <comando>`; entorno reconstruido desde el de la
  sesión; stdin JSON. Salida (`events/user_prompt_submit.rs`, `events/pre_tool_use.rs`): 0 = ok y
  JSON opcional; **2 = bloquea**; cualquier otro código = `Failed` con «hook exited with code N» y
  el turno sigue.
- Payloads de entrada y salida: esquemas generados en `hooks/schema/generated/*.schema.json`.
  `PreToolUse` y `UserPromptSubmit` traen `session_id`, `turn_id`, `transcript_path`, `cwd`,
  `model`, `permission_mode`, y `agent_id`/`agent_type` opcionales; `PreToolUse` trae `tool_name`,
  `tool_input`, `tool_use_id`. No hay campo de esfuerzo. La salida de `UserPromptSubmit` y
  `SubagentStart` admite `hookSpecificOutput.{hookEventName, additionalContext}` con
  `additionalProperties: false` (el mismo JSON que emite `hook_common.emit`).
- Nombres de herramienta en hooks (`core/src/tools/hook_names.rs` y manejadores): shell
  (`exec_command`) = `Bash` con `tool_input.command`; `apply_patch` = `apply_patch` (alias de matcher
  `Write`/`Edit`); MCP = `mcp__<namespace>__<tool>` (`core/src/tools/handlers/mcp.rs`,
  `hook_tool_name_for`, `ensure_mcp_prefix`). El namespace del servidor `local-delegate` se
  sanea a `[A-Za-z0-9_]` en el nombre que ve el modelo (`codex-mcp/src/mcp/mod.rs`,
  `sanitize_responses_api_tool_name`); no se pudo confirmar en vivo si el del hook lleva `-` o `_`,
  así que el matcher acepta los dos (`^mcp__local[-_]delegate__`).
- Code mode: las llamadas anidadas pasan por el despacho normal y disparan sus hooks; solo `wait`
  no (`core/src/tools/code_mode/wait_handler.rs`, comentario de `pre_tool_use_payload`).
- MCP `_meta` de cada `tools/call` (`core/src/mcp_tool_call.rs`): `callId` (el mismo `call_id` que
  recibe `PreToolUse` como `tool_use_id`: `tools/registry.rs`, `apply_pre_tool_use`), `sessionId`,
  `threadId` y `x-codex-turn-metadata`. El cliente MCP se presenta como `codex-mcp-client`
  (`codex-mcp/src/rmcp_client.rs`).

## Medido en Codex 0.169.0 (CODEX_HOME temporal)

- Un `hooks.json` de usuario con un grupo ajeno y nuestros tres grupos (comando
  `"<python>" -I -m local_delegate.hook codex-…`, `timeout` 30): `hooks/list` devuelve los cuatro,
  `source: user`, `trustStatus: untrusted`, `warnings: []`, `errors: []`, y claves
  `…\hooks.json:pre_tool_use:1:0`, `…:user_prompt_submit:0:0`, `…:subagent_start:0:0` (ruta con `\`).
- El `~/.codex` real del usuario tiene su propio `hooks.json` con cuatro grupos ajenos: la
  coexistencia no es teórica.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `install.py` | MCP y `AGENTS.md` para Codex | acción nueva que fusiona `~/.codex/hooks.json`; desinstalación simétrica | `plan_install`, `plan_uninstall` |
| `codex_hooks.py` (nuevo) | — | entradas, fusión, retirada, lectura para `doctor`, manejadores de los hooks | — |
| `hook_entry.py` | despacho de los hooks del plugin de Claude | nombres `codex-*` despachados a `codex_hooks` | `HOOKS`, `main` |
| `hook_common.py` | nota de llamada `toolu_…`, textos | nota con `client`/`model` para Codex; textos `codex.*` es/en | `record_call`, `HOOK_TEXTS` |
| `clients.py` | lee `claudecode/toolUseId` | lee `callId` solo de `codex-mcp-client` | `_tool_use_id_from`, `observe_client` |
| `attribution.py` | resuelve la nota con transcript de Claude | nota de Codex: modelo de la nota, sin transcript ni proyecto | `resolve_call`, `_valid_id` |
| `checks.py` y i18n | 36 checks | check `codex.hooks` (37) | registro `CHECKS` |
| `update.py` | `Repair` por check | `Repair` de `codex.hooks` en `warn` | `REPAIRS` |
| docs | CHANGELOG, README, wiki | declaración de cobertura y límites | — |

## Existing conventions

- `install` no escribe sin plan; `--dry-run` imprime el literal (`Action.literal`); `_backup` guarda
  `.bak` una sola vez; `update_config_json` reescribe JSON solo si cambia y conserva BOM y saltos.
- Los hooks salen siempre con 0 salvo `classify`/`record-read` (`hook.py`, `hook_entry.main`); un
  fallo deja una línea en `hook-failures.jsonl` solo con el tipo.
- `probe` nunca escribe; lo que no se pudo comprobar es `unknown`, nunca `missing`.
- La sesión viaja como `session_key` (hash de un solo sentido), nunca el id en claro.
- La serie de la ventana P-4 (telemetría de hooks) mide Claude Code: no debe recibir líneas de Codex.
- Código en inglés; textos de salida en es/en en `resources/i18n` y `HOOK_TEXTS` (ASCII).

## Dependencies and integrations

- Sin dependencias nuevas. Codex CLI es externo; la entrega solo escribe `~/.codex/hooks.json`.
- El intérprete de los hooks es el del entorno `uv tool` (`claude_plugin.resolve_ld_bin`), igual que
  la entrega por plugin de Claude: sobrevive a `uv tool upgrade` con la misma ruta.

## Risks and unknowns

- Confirmado: sin aprobación del usuario en `/hooks` no corre ningún hook nuestro. El despacho real
  solo lo puede probar el usuario (no se genera `trusted_hash`).
- Supuesto: el `tool_name` del hook para nuestro servidor es `mcp__local_delegate__…` o
  `mcp__local-delegate__…`; el matcher cubre los dos y un test lo ata.
- Supuesto: el formato del `call_id` de una llamada anidada de code mode no se observó; el patrón de
  id acepta `[A-Za-z0-9_-]` de 1 a 128 sin prefijo fijo.
- Que `_meta.callId` llegue al SDK MCP de Python como `ctx.meta["callId"]` se apoya en que
  `claudecode/toolUseId` ya llega así (medido en `coste-api-y-cuota`); la prueba de extremo a
  extremo es la del usuario.
