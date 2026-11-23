# Codex: qué tiene y qué no del mod de Claude Code

El plugin de Claude Code trae un **mod**: código JavaScript que corre dentro de Claude Code y deja
tools fijas, comandos sin modelo y una banda de estado. Codex no carga ese mod (rechaza el
`hooks/hooks.json` del plugin entero, #668) ni tiene un motor equivalente: en Codex no existen
`tool.describe`, `command.run` ni `ui.render`. Esta página dice, superficie por superficie, qué hay
en Codex, qué usa local-delegate y con qué se comprobó.

Versión medida: **Codex CLI 0.169.0** (`openai/codex`, etiqueta `rust-v0.169.0`; las rutas de
código son relativas a `codex-rs/`). Codex Desktop no se probó: comparte el `core` que arma la
entrada del modelo, pero ninguna fila se da por buena en Desktop.

## Cómo leer los estados

- **implementado**: hay código nuestro que lo escribe o lo hace.
- **configurado**: `install` deja la configuración; Codex la acepta al cargar.
- **cargado**: comprobado que Codex lo carga en tiempo de ejecución (no basta con que el fichero
  exista).
- **probado**: comprobado el efecto en Codex real, con la prueba que se indica.
- **no disponible**: Codex no ofrece la superficie; se da la alternativa más cercana.

## La matriz

| Superficie | En Claude Code | En Codex 0.169.0 | Estado en Codex | Evidencia |
| --- | --- | --- | --- | --- |
| Servidor MCP | entrada en `~/.claude.json` | `[mcp_servers.local-delegate]` en `~/.codex/config.toml` | implementado, configurado, cargado | `install.codex_mcp_block`; `doctor` (`scaffold.mcp_codex`); Codex arranca el servidor y, con las tools directas, las pone en la entrada del modelo (`codex debug prompt-input`, abajo); sin ellas quedan tras `tool_search` |
| Instrucciones | bloque en `CLAUDE.md` y skill | bloque en `~/.codex/AGENTS.md` | implementado, configurado | `install`, componente `memory` |
| Hooks | plugin `local-delegate@local-delegate` | `~/.codex/hooks.json`: cuatro hooks, `UserPromptSubmit` (`codex-prompt`), `SubagentStart` (`codex-subagent-start`) y dos de `PreToolUse` (`codex-tool-guard` sobre shell, `apply_patch` y lecturas MCP; `codex-mcp-call` sobre las tools de local-delegate) | implementado, configurado (corren solo tras aprobarlos en `/hooks`), cargado y probado (desde la 0.55.0, #718: Codex CLI 0.171 en Windows despacha los cuatro) | [Hooks de Codex](Integration-install.md#hooks-de-codex), `codex_hooks.SPECS`; `doctor` dice cuántos están aprobados y cuándo despachó cada uno |
| Tools fijadas | `mod/pinned-tools.js`: 4 tools con `isDeferred: false` | `omit_tools_from = ["deferred"]` en la tabla del servidor; **todas** las tools del servidor, no una a una | implementado (opcional), configurado, cargado (`codex debug prompt-input`); el efecto en una sesión real queda para la prueba en vivo | ver [Tools directas](#tools-directas-en-vez-de-tool_search) |
| Comandos sin modelo | `mod/commands.js`: `/local-summarize`, `/local-commit`, `/local-lint` | no hay slash commands de usuario; solo `!comando` (shell sin turno del modelo) | no disponible | ver [Comandos sin modelo](#comandos-sin-modelo) |
| Banda de estado | `mod/status.js`: `ui.render` sobre el prompt | `/statusline` y `tui.status_line`: lista de campos fijos de Codex | no disponible | ver [Barra de estado](#barra-de-estado) |
| Panel de ahorro | panel web del daemon | el mismo panel web (`http://127.0.0.1:9393/`) | implementado (no depende del cliente) | [Savings & metrics](Savings-and-metrics.md) |
| Atribución por sesión | hook `record_call.py` (`PreToolUse`) | `_meta` de cada llamada MCP (`callId`, `sessionId`) más la nota del hook `codex-mcp-call` (`PreToolUse`) | implementado, configurado (desde la 0.53.0), probado con Codex CLI 0.171 en Windows (0.55.0) | #669; [Hooks de Codex](Integration-install.md#hooks-de-codex) («Telemetría global y atribución por sesión»); [Savings & metrics](Savings-and-metrics.md#delegaciones-de-codex) |
| Lectura automática y guard de escritura | mod de lectura y hooks de lectura | hook `codex-tool-guard` (`PreToolUse` con `permissionDecision: "deny"`) sobre shell, `apply_patch` y lecturas MCP | implementado, configurado (desde la 0.53.0), probado con el centinela en Codex CLI 0.171 en Windows (0.55.0: lectura entera resumida, escritura por shell rechazada hasta leer un tramo literal, #724) | #670; [Resumen de lecturas y guard de escritura](Integration-install.md#resumen-de-lecturas-y-guard-de-escritura-en-codex) |

## Tools directas en vez de `tool_search`

**Qué pasa sin hacer nada.** Codex deja toda tool MCP detrás de `tool_search` cuando el modelo
sabe buscar (`core/src/tools/spec_plan.rs`, `apply_mcp_tool_exposure_policy`), y todos los modelos
de su catálogo saben (`codex debug models`: `supports_search_tool: true` en todos). Es el mismo
problema que el mod resuelve en Claude Code: el modelo rara vez busca una tool que no ve.

**La alternativa nativa.** La tabla de un servidor MCP admite `omit_tools_from`
(`config/src/mcp_types.rs`, `RawMcpServerConfig`; también en `core/config.schema.json`). Con
`["deferred"]` las tools de ese servidor van en la lista inicial del modelo. Es **por servidor**:
Codex no deja fijar una tool suelta (la tabla por tool solo admite `approval_mode` y
`output_token_limit`), así que entran las once.

**Cuánto cuesta.** Medido con `codex debug prompt-input` y el servidor de este repo, con la tabla
que escribe `install`: la entrada del modelo pasa de 83 891 a 99 691 bytes, unos 15,8 KB (del orden
de 4 000 tokens) en cada turno.
Por eso va **apagado por defecto** y se enciende a mano:

```bash
local-delegate install --clients codex --codex-direct-tools     # encender
local-delegate install --clients codex --no-codex-direct-tools  # apagar
```

`--codex-direct-tools` añade `"deferred"` a la lista (o la crea); `--no-codex-direct-tools` quita
solo `"deferred"` y deja lo demás que hubieras puesto (una lista que queda vacía desaparece). Sin
ninguno de los dos, `install` y `update` conservan la lista tal cual, también una escrita a mano en
varias líneas (el comentario de fin de línea se pierde, como en los plazos). Si el flag no puede tener efecto (Codex no está entre los clientes, `--no-mcp`
o una entrada tuya que decides no reemplazar), `install` lo avisa. `local-delegate doctor` lo enseña
en la línea de la entrada MCP de Codex («tools directas sin tool_search»): dice lo que pide la tabla,
no lo que Codex hizo (ver el límite de abajo). Abre una sesión nueva de Codex después de cambiarlo.

**Límite conocido.** Con la función `code_mode_only_strict_3p_tools` de Codex encendida, Codex
ignora `omit_tools_from` (`spec_plan.rs`, lo registra en su log y deja las tools diferidas).

**Cómo comprobarlo tú (sin gastar turnos).** `codex debug prompt-input` arma la entrada del modelo
sin llamarlo. El `-c …required=true` solo hace que espere a que el servidor arranque (sin él puede
capturar la entrada antes de que lleguen las tools) y no cambia tu `config.toml`:

```powershell
codex debug prompt-input -c 'mcp_servers.local-delegate.required=true' "hola" |
  Select-String -Pattern '### `mcp__local_delegate__local_' -AllMatches |
  ForEach-Object { $_.Matches.Count } | Measure-Object -Sum
```

Con la opción encendida salen 11 (`mcp__local_delegate__local_summarize`, …); apagada, 0. Esta
misma receta se ejecutó aquí con la tabla que escribe `install` en un `CODEX_HOME` temporal: 11 y 0.

## Comandos sin modelo

**Qué hay en Codex.** Los slash commands de Codex son una lista interna
(`tui/src/slash_command.rs`, `built_in_slash_commands`): no hay forma de registrar uno propio. En
0.169.0 tampoco hay prompts personalizados (`~/.codex/prompts`): no queda ningún cargador en `tui`
ni en `core`. Las skills se invocan por mención y **gastan un turno** del modelo: no son un comando
directo.

**Lo único sin modelo.** El modo shell: una línea que empieza por `!` corre el comando en local,
sin abrir turno del modelo (`tui/src/bottom_pane/chat_composer.rs`; `core/src/tasks/user_shell.rs`)
y deja su salida en el historial como mensaje del usuario
(`core/src/context/user_shell_command.rs`), que el modelo lee en el turno siguiente. Corre **sin
sandbox**.

**Qué falta para usarlo.** local-delegate no tiene todavía un subcomando de CLI que llame a
`local_summarize`, `local_commit_msg` o `local_lint_summary` (los comandos del mod llaman a la tool
por el MCP de Claude Code). Hoy, por `!`, solo sirve lo que el CLI ya hace sin modelo, por ejemplo
`!local-delegate doctor` para ver el estado del backend. Queda como seguimiento.

## Barra de estado

**Qué hay en Codex.** `/statusline` y la clave `tui.status_line` de `config.toml` eligen y ordenan
campos de una lista fija de Codex (`tui/src/bottom_pane/status_line_setup.rs`, `StatusLineItem`:
modelo, directorio, rama, contexto usado, límites, tokens…). No hay campo de comando externo ni de
texto libre; `terminal_title` tiene el mismo límite. No hay, por tanto, forma soportada de enseñar
el estado del backend, la delegación en curso o el ahorro en la barra de Codex.

**Alternativas.** El panel web del daemon (`http://127.0.0.1:9393/`) da el ahorro y las
delegaciones, compartido entre clientes y no por sesión de Codex; `!local-delegate doctor` da el
estado del backend cuando lo pides. Ninguna de las dos es una banda integrada.

## Pruebas en vivo pendientes (las hace la persona usuaria)

1. Con la rama instalada (`uv tool install --force --no-cache <checkout>`), ejecutar
   `local-delegate install --clients codex --codex-direct-tools` y abrir una sesión nueva de Codex.
2. Pedir algo mecánico («resume este fichero en cinco viñetas») y mirar si el modelo llama a
   `local_summarize` sin pasar antes por `tool_search`.
3. `local-delegate doctor`: la línea de la entrada MCP de Codex dice «tools directas».
4. Volver atrás: `local-delegate install --clients codex --no-codex-direct-tools`.
5. Codex Desktop: repetir el punto 2 en la app; hasta entonces ninguna fila vale para Desktop.
