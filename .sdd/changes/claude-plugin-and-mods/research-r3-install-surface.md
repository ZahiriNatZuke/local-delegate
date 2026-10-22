# R3 — Qué escribe hoy local-delegate para Claude Code (y Desktop) y qué cambia con un plugin

Rama `main`, 0.39.0 (`e22e61d`). Solo lectura. Rutas relativas a `D:/Projects/local-delegate/`.
Lo marcado **[a verificar en vivo]** es conducta del cliente que no se midió en esta investigación.

## 0. Resumen en una tabla

| Pieza para Claude Code | Dónde la escribe hoy | Quién | ¿Pasa al plugin? |
|---|---|---|---|
| Entrada MCP `local-delegate` (stdio vía `uvx` o `http` al daemon con cabecera `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`) | `~/.claude.json` → `mcpServers` (ámbito user), por `claude mcp add-json --scope user`; si no hay CLI o el HOME es simulado, editando el fichero | `install.py:2379-2391`, `:2441-2486` | Sí → `.mcp.json` del plugin |
| Scripts de hooks (5 `.py`, stdlib) | `~/.claude/hooks/local-delegate/` (copia del árbol empaquetado) | `install.py:2246-2252` | Sí → `hooks/` del plugin, con `${CLAUDE_PLUGIN_ROOT}` |
| Registro de hooks (2 siempre + 3 con `--enable-read-hook`) | `~/.claude/settings.json` → `hooks` | `install.py:2253-2284`, `:1176-1196` | Sí → `hooks/hooks.json` del plugin |
| Skill `local-delegation` (SKILL.md en el idioma vigente) | `~/.claude/skills/local-delegation/` | `install.py:2286-2295`, `:2215-2226` | Sí → `skills/` del plugin (pasa a llamarse `local-delegate:local-delegation`) |
| Bloque de memoria con la regla | `~/.claude/CLAUDE.md` entre `<!-- local-delegate:begin/end -->` | `install.py:2326-2351` | **No tiene equivalente directo** en un plugin (ver §7) |
| Subagentes (`--agents`, opt-in) | Edita los `~/.claude/agents/*.md` **del usuario**: línea `tools:` + bloque de catálogo | `install.py:2317-2324`, `agents.py:184-` | No: son ficheros del usuario; el plugin puede traer agentes propios, no editar los ajenos |
| Migración de nombres retirados | `settings.json` → `env` y ficheros interruptor de `~/.claude/` | `install.py:2013-2057`, llamada en `:2243-2244` | Se queda en el CLI |
| Preferencia de idioma | `language.json` en `LOG_DIR` | `install.py:1755-1816` | Se queda (la leen daemon y hooks) |
| Autocompletado de la shell | Perfiles de shell + ficheros en el directorio de datos | `install.py:816-1092`, `cli.py:231-260` | Se queda: no es de ningún cliente |
| Variables `LD_HOOK_*` | **`install` no las escribe**: las pone el usuario (en el `env` de `settings.json` o en el entorno del lanzador) | doc `docs/wiki/Configuration.md:566-600` | El plugin no puede poner `env` de sesión **[a verificar en vivo]**; seguirán siendo del usuario |
| Claude Desktop | **Nada.** Solo lo lee `doctor` (`service.desktop_auth`) | `checks.py:1363-1440` | Ver §5 |

## 1. `install` para Claude Code

### 1.1 Entrada MCP

| Qué | fichero:línea | Detalle |
|---|---|---|
| Nombre del servidor | `install.py:53` | `SERVER_NAME = "local-delegate"`; de él salen los nombres de tool `mcp__local-delegate__local_*` |
| Entrada stdio | `install.py:1288-1297`, `:1250-1270` | `uvx --from local-delegate-mcp[==ver] local-delegate-mcp`; `env` con `LOCAL_DELEGATE_BASE_URL`, `LOCAL_DELEGATE_AUTOSTART=0`, `LOCAL_DELEGATE_API_KEY=${LOCAL_DELEGATE_API_KEY}` (referencia, nunca el valor) |
| Entrada http | `install.py:1281-1287`, URL en `:1238-1247` | `{"type":"http","url":"http://127.0.0.1:9393/mcp"}` y, con `--web-token-env`, `headers.Authorization = "Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"` (`WEB_TOKEN_VAR`, `:1235`) |
| Cabecera conservada si no se pasa el flag | `install.py:1310-1343`, `:2364-2369` | El flag tiene tres estados (`Options.web_token_env`, `:1681`) |
| Plazos (`timeout`) conservados | `install.py:1352-1385`, `:2381-2382` | La CLI se comprueba después; si los perdió, se escribe el fichero (`:2469-2475`) |
| Registro | `install.py:2441-2486` | `claude mcp remove --scope user` + `claude mcp add-json --scope user`; fallback: `~/.claude.json` `mcpServers[local-delegate]` |
| CLI apagada con HOME simulado o `--no-client-cli` | `cli.py:104-107` | `claude mcp … --scope user` escribe siempre en el `~/.claude.json` real |
| Daemon tras instalar en http | `cli.py:331-347` | `update.restart_daemon` |

### 1.2 Hooks

| Qué | fichero:línea | Detalle |
|---|---|---|
| Siempre | `install.py:73-76` | `UserPromptSubmit` → `suggest_delegate_prompt.py`; `PreToolUse` matcher `mcp__local-delegate__.*` → `record_call.py` |
| Con `--enable-read-hook` | `install.py:77`, `:82`, `:87-91`, `:2257-2260` | `PreToolUse/Read` y `PreToolUse/mcp__.+__(read_[a-z_]*\|get_file_contents)` → `suggest_delegate_read.py --enabled`; `PreToolUse/Bash\|PowerShell` → `suggest_delegate_shell.py --enabled` |
| El argumento es el interruptor | `install.py:130-142` | `READ_HOOK_FLAG = "--enabled"`; el script lo lee en `suggest_delegate_read.py:134-143` |
| Comando | `install.py:1096-1113` | `python "<ruta con barras />/script.py" [--enabled]`, ruta siempre citada (con `\` desnudas el shell las comía y bloqueaba cada prompt) |
| Ejecutable | `install.py:195-202` | `python` (Windows) / `python3`: resuelto por PATH, nunca `sys.executable` (uvx es efímero); sobreescribible con `--python` (`cli.py:97`) |
| Escritura idempotente | `install.py:1176-1231` | `merge_hook_settings` quita primero todo lo nuestro (`_is_ours`, `:1133-1148`: ruta `hooks/local-delegate` o nombre de script, incluidos retirados `:115-120` y el formato viejo con `args`) |
| Scripts huérfanos en la raíz de `hooks/` | `install.py:2067-2160` | se borran solo por nombre conocido |
| `read_hook_registered` | `install.py:1151-1173` | lo usa `update` para no apagar el hook de lectura al reponer |

### 1.3 Skill, memoria, agentes

| Qué | fichero:línea |
|---|---|
| Copia de la skill con `SKILL.md` en el idioma (`SKILL.en.md` como variante) | `install.py:2209-2226`, `:2286-2295` |
| Skills retiradas (`delegacion-local`) | `install.py:128`, `:2112-2138` |
| Bloque en `CLAUDE.md` | `install.py:47-49`, `:2326-2351`; fuente `resources/memory/local-delegate[.en].md` |
| `--agents`: componente opt-in | `cli.py:33-35`, `install.py:2314-2324` |
| Qué hace con cada agente | `agents.py:34-38` (`ANCHOR = mcp__local-delegate__local_delegate`, `TOOL_PREFIX`, marcadores de catálogo), `:127` (`is_delegator`), `:134-150` (añade tools a la línea `tools:`), `:152-182` (inserta/reemplaza el bloque de catálogo), `:195-` (`pending`) |
| Refresco del catálogo de agentes en `update` | `install.py:417-458` (`plan_catalog_refresh`), `update.py:336-341` |

### 1.4 Variables de entorno

`install` **no escribe** ninguna variable de hooks. Solo **migra** nombres retirados en el `env` de
`settings.json` (`install.py:1818-2057`). Las variables que leen los hooks
(`resources/hooks/hook_common.py`): `LD_HOOK_ENABLED` (`:45`), `LD_HOOK_TELEMETRY_LOG` (`:97`),
`LOCAL_DELEGATE_BASE_URL`/`LOCAL_DELEGATE_API_KEY` (`:208`, `:226-227`, sondeo de salud del backend),
`LD_HOOK_READ_SWITCH_FILE` (`:288`), `LD_HOOK_READ_BLOCK` (`:303`), `LOCAL_DELEGATE_LOG_DIR` (`:322`),
`LOCAL_DELEGATE_LANG` (`:467`), `LOCAL_DELEGATE_LONG_INPUT_CHARS` y `LOCAL_DELEGATE_MODEL_*`
(`:537-543`); y en los scripts `LD_HOOK_READ_ENABLED` (`suggest_delegate_read.py:143`),
`LD_HOOK_READ_SUGGEST_KB`/`STRONG_KB` (`:260-261`, `suggest_delegate_shell.py:150`). Todas salen
del entorno que hereda el proceso del hook (el del lanzador de Claude Code más el `env` de
`settings.json`), no de nada que ponga el instalador.

### 1.5 Claude Desktop

`install` no lo toca (decisión documentada en `checks.py:1366-1370`; backlog §1.1 fase B
pendiente: que `install` escriba la entrada). Lo único que hay:
- `checks.Context.claude_desktop_config` (`checks.py:440-453`): `%APPDATA%/Claude/claude_desktop_config.json` (o equivalente macOS/Linux), derivado del HOME.
- `service.desktop_auth` (`checks.py:1345-1440`, registro `:2410-2411`): lee `mcpServers.local-delegate`, acepta la forma `mcp-remote` (URL y `--header Authorization:` dentro de `args`) o `{url, headers}`, y prueba el token contra el puerto con `daemon.daemon_accepts_token` (`daemon.py:143-161`).
- Los hooks no existen en Desktop (`docs/wiki/Configuration.md:568-570`).

## 2. `doctor`: checks que miran estas piezas

Registro en `checks.py:2333-2418`. `Context.hooks_dir` = `~/.claude/hooks/local-delegate` (`:469-471`).

| Id | Grupo | Probe (fichero:línea) | Qué valida |
|---|---|---|---|
| `client.presence` | environment | `checks.py:561-574` | existen `~/.claude`, `~/.codex`, dir de opencode |
| `client.observed` | environment | `checks.py:628-` | clientes vistos por el daemon (`clients.jsonl`) |
| `config.deprecated_names` | environment | `checks.py:1908-` | nombres viejos en el entorno, en el `env` de `settings.json`, interruptores y telemetría de hooks |
| `config.claude_settings` | environment | `checks.py:1996-` | `settings.json` en UTF-8 y sin copias de la migración |
| `scaffold.hook_files` | scaffold | `checks.py:768-812` | están los scripts empaquetados en `hooks/local-delegate/` y **son de esta versión** (comparación de bytes, `_differs` `:533`) |
| `scaffold.hook_orphans` | scaffold | `checks.py:815-847` | scripts nuestros sueltos en la raíz de `~/.claude/hooks/` |
| `scaffold.hook_settings` | scaffold | `checks.py:850-908` | hay hooks nuestros en `settings.json` (`install._is_ours`); `warn` si alguno está en el formato viejo con `args`. **No** compara eventos ni matchers con los esperados |
| `scaffold.skill` | scaffold | `checks.py:911-958` | `SKILL.md` presente en `~/.claude/skills/local-delegation` y en el de opencode. No compara contenido |
| `scaffold.memory` | scaffold | `checks.py:961-1004` | bloque en `CLAUDE.md`/`AGENTS.md` y que sea el empaquetado |
| `scaffold.mcp_claude` | scaffold | `checks.py:1055-1081` | `mcpServers.local-delegate` en `~/.claude.json`; enseña modo, URL/comando y plazos |
| `scaffold.mcp_codex` / `scaffold.mcp_opencode` | scaffold | `checks.py:1084-`, `:1138-` | (Codex/opencode: fuera de alcance, no cambian) |
| `scaffold.shell_completion` | scaffold | `checks.py:2212-` | autocompletado (no depende del cliente) |
| `service.credential` | service | `checks.py:1170-1226` | si el backend pide key, que las entradas MCP sean http (vía daemon) |
| `service.daemon_auth` | service | `checks.py:1263-1337` | si el puerto del daemon pide token, que cada entrada lleve cabecera y la variable esté en el entorno |
| `service.desktop_auth` | service | `checks.py:1363-1440` | el token de la entrada de Desktop entra al daemon |

Nadie mira `~/.claude/agents` (lo dice `update.py:336-338`).

## 3. `update`: reparaciones

`REPAIRS` en `update.py:171-227`; aplicación en `plan_repairs` (`update.py:280-367`), que llama a
`install.plan_install` por par (componente, cliente) y deduplica por `(kind, target)` (`:343-353`).

| Check | Estados que repara | Componente → cliente | Nota |
|---|---|---|---|
| `scaffold.hook_files` | missing, warn | hooks → claude | warn = scripts viejos: así se refrescan los hooks al actualizar |
| `scaffold.hook_settings` | missing, warn | hooks → claude | conserva el hook de lectura con `read_hook_registered` (`update.py:315-318`) |
| `scaffold.hook_orphans` | warn | hooks → claude | |
| `scaffold.skill` | missing, warn | skill → presentes | |
| `scaffold.memory` | missing, warn | memory → presentes | |
| `scaffold.mcp_claude` | missing | mcp → claude | modo inferido de las otras entradas o del daemon (`_infer_mcp_mode`, `:258-277`) |
| (fuera de la tabla) catálogo de agentes | — | `update.py:339-341` | |
| (fuera de la tabla) pin `==versión` | — | `update.py:520-539` | reescribe `local-delegate-mcp==X` en `~/.claude.json` y `~/.codex/config.toml` |
| (fuera de la tabla) migración de nombres | — | `update.py:890-901` | primer paso, siempre |
| (fuera de la tabla) autocompletado | — | `update.py:391-433` | |

`service.credential`, `service.daemon_auth`, `service.desktop_auth` solo imprimen su pista (`update.py:153-170`, `:355-366`).

## 4. `uninstall`

`plan_uninstall` (`install.py:2644-2764`), vía `cli.py:217-328` con `uninstall=True`:

| Componente | Qué retira | fichero:línea |
|---|---|---|
| hooks | nuestras entradas de `settings.json` (`strip_hook_settings`) y el directorio `hooks/local-delegate/` | `:2652-2672` |
| skill | `~/.claude/skills/local-delegation` y skills retiradas | `:2674-2688` |
| memory | el bloque entre marcadores de `CLAUDE.md` | `:2704-2721` |
| mcp | `claude mcp remove --scope user local-delegate`, o borra la clave de `~/.claude.json` | `:2723-2732`, `:2782-2806` |
| idioma | `language.json`, solo en desinstalación completa | `:2759-2763`, `:2768` |
| autocompletado | perfiles y ficheros | `cli.py:231-260`, `install.py:990-1092` |
| **agents** | **nada**: no hay rama para `agents`; las tools y el bloque de catálogo quedan en los agentes del usuario | (ausencia en `:2644-2764`) |

No retira huérfanos de la raíz de `hooks/` ni el `env` de `settings.json`.

## 5. Modelo de clientes y abstracción que haría falta

**`clients.py` no es un registro de destinos**: es el observador de qué cliente MCP se conecta al
daemon (`clients.py:1-24`, log `clients.jsonl`). El «registro» de destinos está repartido:

| Dónde | fichero:línea | Forma |
|---|---|---|
| Lista de clientes del CLI | `cli.py:36`, `:40-44` | tupla `("claude","codex","opencode")` |
| Detección | `install.py:178-192` (`present_targets`) | por directorio |
| Ramas por cliente en el plan | `install.py:2246-2437`, `:2644-2757` | `if "claude" in opts.targets` por componente |
| Diagnóstico | `checks.py:561-566` (`_client_dirs`), checks `scaffold.*` por cliente | |
| Reparación | `update.py:171-227` | `Repair(..., targets={"claude"})` |
| Entrada MCP por cliente | `install.py:1273-1297` (claude), `:1405-` (codex TOML), `:1613-` (opencode) | |
| Desktop | solo `checks.py:440-453` | sin rama en `install` |

**Propuesta de abstracción** (para la spec): separar **cliente** de **vía de entrega**. Claude Code
pasa a tener dos vías, `settings` (la actual) y `plugin`; Codex y opencode solo tienen `settings`
y no cambian. Un único dato —«¿cómo se entrega cada componente a este cliente?»— que consulten
los tres verbos:

- `install`: con `claude` en vía `plugin`, no emite las acciones hooks/skill/mcp de `~/.claude` y en su lugar instala/activa el plugin (o lo indica), y **retira** las piezas de la vía `settings` (ver §7).
- `doctor`: los checks `scaffold.hook_*`, `scaffold.skill`, `scaffold.mcp_claude` cambian de pregunta según la vía («¿está el plugin instalado y activo, y es de esta versión?») y aparece uno nuevo de **duplicados** (piezas en las dos vías a la vez).
- `update`: `REPAIRS` por vía; con vía `plugin` no se repone nada en `settings.json` (si no, reintroduce el doble hook), y el refresco de versión es el del plugin, no el `pin` de `~/.claude.json`.

La vía se **deduce del disco** (plugin presente/activo) más un flag explícito de `install`, igual que
el modo MCP se deduce hoy (`update.py:258-277`), para que `update` no necesite flags.

## 6. Scripts de hooks

| Aspecto | Hoy | fichero:línea |
|---|---|---|
| Origen | `src/local_delegate/resources/hooks/` (`hook_common.py`, `record_call.py`, `suggest_delegate_prompt.py`, `suggest_delegate_read.py`, `suggest_delegate_shell.py`, 1 347 líneas) | `install.py:145-147` |
| Destino | `~/.claude/hooks/local-delegate/` | `install.py:54`, `:2247` |
| Invocación | `python "C:/Users/…/.claude/hooks/local-delegate/x.py" [--enabled]`, string de shell | `install.py:1096-1113` |
| Dependencias | solo stdlib; importan `hook_common` de su propio directorio (`suggest_delegate_prompt.py:10`) | portables tal cual a un plugin |
| Textos | catálogo es/en dentro de `hook_common.HOOK_TEXTS` (`hook_common.py:~330-421`); idioma por `LOCAL_DELEGATE_LANG` o `language.json` en `LOG_DIR` (`:425-470`) | no dependen de la ruta de instalación |
| Red | sondeo de salud del backend en `LOCAL_DELEGATE_BASE_URL` con `LOCAL_DELEGATE_API_KEY` (`hook_common.py:200-283`) | |
| Ficheros que escriben | telemetría (`LD_HOOK_TELEMETRY_LOG`), notas de bloqueo y de llamada en `LOG_DIR` (`hook_common.py:601-723`) | el daemon las lee para la atribución |
| Lo que `install` reutiliza del paquete | `install.py:44` importa `resources.hooks.hook_common` (idioma) | |

En un plugin: `hooks/hooks.json` con `python "${CLAUDE_PLUGIN_ROOT}/hooks/x.py"`. Sigue haciendo
falta un `python` en el PATH: el plugin no trae intérprete **[a verificar en vivo: quoting de
`${CLAUDE_PLUGIN_ROOT}` con espacios en Windows y qué shell usa el hook de plugin]**.

## 7. Riesgos de migración

| Riesgo | Por qué | Qué debe detectar `doctor` | Qué debe hacer `update`/`install` |
|---|---|---|---|
| **Doble hook** | Los hooks de plugin se suman a los de `settings.json`; los comandos difieren (ruta del plugin vs `~/.claude/hooks/local-delegate`), así que no se deduplican **[a verificar en vivo]**. Cada prompt sugeriría dos veces y `record_call` anotaría dos veces | nuestras entradas en `settings.json` (`install._is_ours`) **y** plugin activo → `warn` | retirar con `strip_hook_settings` (`install.py:1199`) y borrar `hooks/local-delegate/`; y no volver a reponerlas (hoy `scaffold.hook_settings` en `missing` las repondría: `update.py:181-188`) |
| **Doble MCP** | Un MCP de plugin se registra con otro nombre (**[a verificar]**: `plugin:local-delegate:local-delegate`, tools `mcp__plugin_local-delegate_local-delegate__local_*`); el de `~/.claude.json` sigue → 11 tools duplicadas y dos conexiones | `mcpServers.local-delegate` en `~/.claude.json` **y** plugin activo | `claude mcp remove --scope user local-delegate` (`install.py:2782`); `scaffold.mcp_claude` en `missing` no debe reponerla (`update.py:215`) |
| **Cambio del nombre de las tools** | Si el prefijo pasa a ser `mcp__plugin_…__`, dejan de casar: el matcher de `record_call` (`install.py:75`), el `ANCHOR`/`TOOL_PREFIX` de agentes (`agents.py:34-35`), la lectura de transcripts para coste/atribución (`transcripts.py:30`, `:154-160`, usada por `recompute.py:271-286`), `scripts/_claude_bench.py`, y las tools de los agentes del usuario (`tools: mcp__local-delegate__…`) | — | aceptar los dos prefijos en esas cinco superficies, o fijar el nombre del servidor; **es lo primero que hay que medir** |
| **Skill duplicada** | `~/.claude/skills/local-delegation` y la del plugin (`local-delegate:local-delegation`) se ven las dos | las dos presentes | borrar la de `~/.claude/skills` |
| **Memoria en `CLAUDE.md`** | Un plugin no escribe `CLAUDE.md`; la regla tendría que ir en la skill o en un hook `SessionStart` | — | decidir: o se mantiene el bloque como hoy (el CLI sigue escribiéndolo) o se retira y el plugin inyecta contexto |
| **Hook de lectura y su interruptor** | Hoy el registro con `--enabled` es el interruptor (`install.py:130-142`); en un plugin los hooks van fijos en `hooks.json` | — | mover el interruptor a configuración (p. ej. `userConfig` del plugin o fichero) **[a verificar qué ofrece el plugin]**; `read_hook_registered` deja de servir para recordar la elección |
| **Versión de los hooks** | `scaffold.hook_files` compara con el paquete Python; con plugin, los scripts vienen con la versión del plugin, no con la de `uv tool` | desfase plugin ↔ paquete (`cli.published`/versión del daemon) | `update` no puede reescribir la caché del plugin: tendría que decir `claude plugin update …` o hacerlo |
| **Pin `==versión`** | `plan_pin` reescribe `~/.claude.json` (`update.py:520-539`); con plugin la entrada vive en `.mcp.json` del plugin | — | quitar Claude Code de `plan_pin` en vía `plugin` |
| **Cabecera de token** | `install` escribe `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`; en `.mcp.json` de plugin hace falta que la expansión `${VAR}` funcione igual **[a verificar en vivo]** | `service.daemon_auth` tendría que leer la entrada del plugin | — |
| **Agentes del usuario** | `--agents` añadió `mcp__local-delegate__*` a sus `tools:`; con otro prefijo quedan apuntando a tools inexistentes | agentes con el prefijo viejo | o mantener el nombre o reescribir con `agents.process`; `uninstall` hoy no los limpia (§4) |
| **HOME simulado / CLI `claude`** | `claude plugin install` probablemente también escribe en el HOME real, como `claude mcp --scope user` (`cli.py:104-107`) **[a verificar]** | — | mismo apagado que `use_cli` |
| **Codex y opencode** | Comparten `plan_install`/`REPAIRS`/checks con Claude | — | la vía es por cliente; ellos siguen en `settings` y sus tests no deberían cambiar |

## 8. Tests por pieza

| Pieza | Tests |
|---|---|
| Comando de hook, `_is_ours`, `merge/strip_hook_settings`, `orphan_hook_scripts`, `--enable-read-hook`, `plan_uninstall` | `tests/test_install.py`, `tests/conftest.py`, `tests/test_hook_shell_absolute_path.py` |
| Scripts de hooks | `tests/test_hook_boundaries.py`, `test_hook_common.py`, `test_hook_legacy_names.py`, `test_hook_recipes.py`, `test_hook_shell.py`, `test_hook_texts.py`, `test_hooks_telemetry_api.py` |
| Entrada MCP, cabecera, plazos | `tests/test_install.py`, `test_install_header.py`, `test_install_timeouts.py`, `test_config_json_safety.py` (`_register/_unregister_claude_mcp`), `test_checks.py` |
| Selección de clientes, HOME simulado | `tests/test_install_clients.py` |
| Skill, idioma, catálogo de agentes | `tests/test_install_language.py`, `test_skill_parity.py`, `test_install_english.py` |
| Agentes | `tests/test_agents.py` (+ `test_update.py`) |
| Migración de nombres | `tests/test_install.py`, `test_checks.py`, `test_retired_env_names.py` |
| Checks `scaffold.*`, `service.*`, `desktop_auth`, `claude_settings` | `tests/test_checks.py`, `test_doctor.py`, `test_doctor_claude_settings.py` |
| `REPAIRS`, `plan_repairs`, `plan_pin`, `read_hook_registered` | `tests/test_update.py`, `test_update_completion.py`, `test_install_timeouts.py` |
| Prefijo `mcp__local-delegate__` | `tests/test_agents.py`, `test_attribution.py`, `test_f1_conformance.py`, `test_install.py`, `test_install_english.py`, `test_transcripts.py` |
| opencode (no debe cambiar) | `tests/test_install_opencode.py` |
| E2E del instalador | `scripts/check_install_e2e.py`, `scripts/check_install_handshake.py` |
| Wiki (textos de instalación) | `tests/test_wiki.py`; páginas `docs/wiki/Integration-install.md`, `Configuration.md` |

## Llamadas `local_*` de esta investigación

- `local_explain_code(path=src/local_delegate/agents.py)` — qué toca `--agents` y si hay reversión.
- `local_summarize(path=<vault>/investigacion-mods-claude-code-2026-10-21.md)` — contexto previo de mods.

El resto se hizo con `grep`/`sed` acotados y lecturas por franjas: hacían falta números de línea
exactos, que los resúmenes del modelo local no dan.
