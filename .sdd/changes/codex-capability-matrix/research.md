# Research: Codex: matriz de capacidades y alternativas para barra, comandos sin modelo y tools fijadas (#671)

Fuente de Codex: `openai/codex`, etiqueta `rust-v0.169.0` (clon parcial ya existente de la sesión de
#669, solo lectura; rutas relativas a `codex-rs/`). Codex CLI instalado: `codex-cli 0.169.0`. Las
pruebas en tiempo de ejecución usan un `CODEX_HOME` temporal del scratchpad, nunca `~/.codex`.

## Current behavior

### Lo que hace el mod de Claude Code

- `mod/pinned-tools.js:55-63`: `tool.describe` con `isDeferred: false` saca cuatro tools
  (`DEFAULT_PINNED`) de detrás de ToolSearch.
- `mod/commands.js:345-386`: `/local-summarize`, `/local-commit`, `/local-lint` con `command.run`,
  sin turno del modelo; llaman a la tool con `$.mcp.call` y dejan la salida en el transcript.
- `mod/status.js` (`ui.render` sobre `AbovePrompt`): banda propia con sesión, progreso, backend y
  ahorro.

### Lo que ofrece Codex 0.169.0

- **Tools diferidas.** `core/src/tools/spec_plan.rs:229-322` (`apply_mcp_tool_exposure_policy`):
  si el modelo tiene `supports_search_tool`, toda tool MCP queda `Deferred` (tras `tool_search`)
  salvo que su servidor declare `omit_tools_from` con `deferred`. Todos los modelos del catálogo
  (`codex debug models` con `CODEX_HOME` vacío) traen `supports_search_tool: true`.
  `omit_tools_from` es clave de `[mcp_servers.<nombre>]` (`config/src/mcp_types.rs:447`,
  `RawMcpServerConfig`, `deny_unknown_fields`) y está en `core/config.schema.json`. Es **por
  servidor**: no se puede fijar una tool suelta (`McpServerToolConfig` solo tiene `approval_mode` y
  `output_token_limit`, `mcp_types.rs:84-92`).
- **Prueba en tiempo de ejecución** (`codex debug prompt-input`, que construye la entrada visible
  para el modelo sin llamarlo), con el servidor real de este repo por stdio y `CODEX_HOME` temporal:
  sin la clave, 0 tools `mcp__local_delegate__*` en el prompt; con
  `-c 'mcp_servers.local-delegate.omit_tools_from=["deferred"]'`, las 11 aparecen como
  declaraciones de `exec` (83 889 → 99 689 bytes, unos 15,8 KB ≈ 4 000 tokens por turno).
- **Barra de estado.** `tui.status_line` (`config/src/types.rs:984-993`) es una lista ordenada de
  identificadores fijos (`tui/src/bottom_pane/status_line_setup.rs:45-170`, enum `StatusLineItem`:
  modelo, directorio, rama, contexto, límites, tokens, etc.). No hay elemento de comando externo ni
  texto libre. `/statusline` solo elige de esa lista. Lo mismo `terminal_title`.
- **Comandos sin modelo.** Los slash commands son una lista interna
  (`tui/src/slash_command.rs`, `built_in_slash_commands`; `bottom_pane/slash_commands.rs:1`); en
  0.169.0 no hay cargador de prompts personalizados (`~/.codex/prompts`) en `tui` ni `core`. Las
  skills se invocan con mención y consumen un turno. Lo único sin modelo es el modo shell `!`
  (`tui/src/bottom_pane/chat_composer.rs:1797`; `core/src/tasks/user_shell.rs`): corre un comando
  local sin sandbox y deja la salida en el historial como fragmento de usuario
  (`core/src/context/user_shell_command.rs`), sin abrir turno del modelo.
- **Resto de filas de la matriz (ya entregadas por otros cambios, se citan, no se reprueban):**
  entrada MCP (`install.py:1625-1663`, `codex_mcp_block`; check `scaffold.mcp_codex`,
  `checks.py:1240`), instrucciones (`install.py`, componente `memory` → `~/.codex/AGENTS.md`,
  README l. 394), hooks (`codex_hooks.SPECS`, `codex_hooks.py:61-64`; prueba de carga en
  `.sdd/changes/codex-native-hooks/research.md`), panel (daemon, independiente del cliente,
  `docs/wiki/Savings-and-metrics.md`), atribución (#669) y lectura (#670) en curso.
- **Prueba con la tabla del instalador** (T5): `codex_mcp_block` + `codex_exposure` +
  `upsert_codex_mcp` en un `CODEX_HOME` temporal (solo `command`/`args` cambiados al servidor del
  checkout) y `codex debug prompt-input -c 'mcp_servers.local-delegate.required=true'`: 11 tools y
  99 691 bytes con la opción, 0 tools y 83 891 bytes sin ella. Sin `required=true` sale 0 en los dos:
  `prompt-input` no espera al arranque del servidor (dato para la receta de comprobación).
- **CLI de local-delegate.** No hay subcomando que llame a `local_summarize`/`local_commit_msg`/
  `local_lint_summary` (`cli.py`, lista de `add_parser`). `doctor` sí da el estado del backend.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `install.py` (`codex_mcp_block`, `existing_timeouts`) | escribe y conserva la tabla `[mcp_servers.local-delegate]` | conservar y escribir `omit_tools_from` | `install.py:1572-1663`, `3123-3141` |
| `cli.py` (`install`, `_install_options`) | opciones de `install` | `--codex-direct-tools` / `--no-codex-direct-tools` | `cli.py:88-112`, `1678-1751` |
| `checks.py` (`_probe_mcp_codex`) | línea de `doctor` de la entrada de Codex | decir si las tools van directas | `checks.py:1240-1265` |
| i18n `cli`, `install`, `doctor` | textos es/en | claves nuevas | `resources/i18n/{es,en}` |
| `docs/wiki/` | doc de integración | página nueva `Codex-capabilities.md` | — |
| `codex_hooks.SPECS` | hooks de Codex | sin cambio: #671 no necesita hook nuevo | `codex_hooks.py:61-64` |

## Existing conventions

- Lo que el usuario puso en la tabla de Codex se conserva tal cual, como texto TOML
  (`existing_timeouts`, `tests/test_install_timeouts.py`).
- Tres estados en las opciones que tocan una entrada existente (`--web-token-env`): sin flag se
  conserva.
- `install.py` y `cli.py` con CRLF; `checks.py`, i18n y tests con LF.

## Dependencies and integrations

- Sin dependencias nuevas. Codex lee la clave; nada más la usa.

## Risks and unknowns

- Codex Desktop no se probó (la entrada del modelo la arma el mismo `core`, pero no se ejecutó).
- Coste: fijar las 11 tools suma unos 4 000 tokens por turno (cacheables); por eso es opcional.
- Con `code_mode_only_strict_3p_tools` Codex ignora la clave (`spec_plan.rs:271-281`).
