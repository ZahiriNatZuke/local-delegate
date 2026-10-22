# F2-live — Medición en vivo de F2

Lote «Medición en vivo de F2» (plan, ola 3b, líneas ~650-676). Windows 11, Claude Code 2.1.308
(`~/.local/bin/claude.exe`), daemon real 0.39.0 en `127.0.0.1:9393` (sin reiniciar), código de
`main` en `5c771c7` (#398–#404) en el worktree `D:/Projects/ld-wt-f2-live`, `register.js` generado
con `uv run python scripts/build_mod.py` (no se commitea: lo mete en el build otro lote).

## Criterio fijado ANTES de medir (2026-10-22, entre 05:17Z y 05:18Z: después de una sola corrida de prueba del montaje, `/f2bash 2` a las 05:17:24Z, y antes de la primera corrida de medida, a las 05:18:52Z)

| Punto | Cumple si… |
|---|---|
| Sobrecarga de los hooks siempre declarados | mediana(con plugin) − mediana(sin plugin) ≤ **+150 ms** **y** p95(con) − p95(sin) ≤ **+300 ms**, sobre las llamadas `Bash` «en caliente» (se descarta la primera de cada sesión, que arranca el shell; se informa aparte). 3 repeticiones (`--repeat 3`), cada una con 2 sesiones por brazo intercaladas (con, sin, con, sin) de 10 llamadas: 54 muestras en caliente por brazo. Si se supera, no se arregla aquí: se informa con cifras. |
| REQ-003, latencia | p95 ≤ 300 ms por invocación, con ≥ 20 invocaciones de cada hook (`prompt`, `record-call`, `read`, `mcp-read`, `shell`) lanzadas como las lanza el motor (`<python> -I -m local_delegate.hook <nombre>`, JSON por stdin). Se contrasta con el tiempo que el propio motor anota en `--debug-file` («finished with status 0 (N ms)»). |
| REQ-003, `ld_bin` roto | Con `ld_bin` = ejecutable inexistente y con `ld_bin` = intérprete de la 0.39 instalada (sin `local_delegate.hook`): el prompt llega a la API (sin sesión: `Not logged in`, no `blocked by hook`) y una `Bash` del driver devuelve su salida. |
| REQ-015 | En la misma sesión, una llamada del mod (`/local-summarize`) y una del modelo: en el log de uso, la del mod con `tool_use_id` `toolu_plugin_…` y la del modelo con otro `tool_use_id`; `/api/stats` (código de `main`, con `include_tests=1` y el rango de la ventana) da `mod_calls` = 1 de 2. |
| REQ-016 | (a) todas las piezas a `off` por `userConfig` y (b) un `register.js` que lanza al cargar: el hook `record-call` corre (lo anota el motor y la fila del log trae `caller_src` de hook) y la llamada MCP devuelve resultado. |
| Puente de Desktop | `local-delegate desktop-bridge` lanzado por stdio con SOLO la lista fija de variables de r5: `initialize`, `tools/list` (con las tools `local_*`) y `local_status` responden sin error contra el daemon real; el token no aparece en ninguna salida. |

**Añadido hacia las 05:20Z, tras la primera tanda (05:18:52–05:19:23Z) y antes de la segunda (desde
05:20:45Z)**: la primera tanda midió
la capa «activo» de lectura **apagada** (en esta PC aún no existe `LOG_DIR/read-hook.json`, así que
`read_switch.enabled()` da `False` y la entrada `shell` sale tras importar solo `read_switch`). Se
añade un brazo «A» = plugin con la capa **encendida** (`LD_HOOK_READ_ENABLED=1` en el entorno del
`claude` hijo; el bloqueo real de esta PC sigue como está), con el mismo criterio (+150 / +300 ms)
y el mismo diseño (3 × 2 sesiones intercaladas A, N, de 10 llamadas).

## Veredicto

| Punto | Veredicto | Cifra clave |
|---|---|---|
| Sobrecarga de los hooks siempre declarados | **cumple** | +80 ms mediana / +79 ms p95 (capa apagada); +125,5 / +124 ms (capa encendida) |
| REQ-003, latencia | **cumple** | peor p95 116,4 ms (tope 300) |
| REQ-003, `ld_bin` inexistente y 0.39 | **cumple** | el prompt y la `Bash` pasan; el control con salida 2 bloquea |
| REQ-015 | **cumple** | `mod_calls: 1` de `calls: 2` en la misma sesión |
| REQ-016 | **cumple** | `record-call` con estado 0 y respuesta del MCP, con las piezas a `off` y con `register.js` roto |
| Puente del chat de Desktop | **cumple** | `initialize`, `tools/list` (11) y `local_status` sin error; token fuera de toda salida |
| `process.run` en la pestaña Code | **pendiente** | tras instalar la 0.40.0 (comando abajo) |

## Montaje

- **Sin cuenta y sin cuota para casi todo** (mismo método que T0): `CLAUDE_CONFIG_DIR` aislado del
  scratchpad, sin sesión iniciada. Las llamadas a tools las dispara un mod de prueba
  (`F2-live/drv/`, comandos `/f2bash N` y `/f2mcp <ruta>`) con `$.tool.call`, que pasa por todos los
  `PreToolUse`, el permiso y la tool igual que una llamada del modelo, pero sin turno. Cada llamada
  se cronometra con `Date.now()` alrededor de `$.tool.call`.
- **`userConfig` con `--plugin-dir`**: `settings.json` del config aislado con
  `pluginConfigs["local-delegate@inline"].options` (`ld_bin`, `language` e interruptores). Funciona:
  el motor sustituye `${user_config.ld_bin}` y el latido sale en
  `<config>/plugins/data/local-delegate-local-delegate/heartbeats/`.
- **MCP** en el config aislado: `--strict-mcp-config --mcp-config F2-live/mcp.json` (entrada `http`
  con `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`, que expande Claude Code; el token no se escribe).
- `ld_bin` bueno = `D:/Projects/ld-wt-f2-live/.venv/Scripts/python.exe` (código de `main`).
- **Solo REQ-015** necesita un turno del modelo: config REAL (sin `CLAUDE_CONFIG_DIR`), `--plugin-dir`,
  `--settings <fichero>` con el mismo `pluginConfigs`, `--strict-mcp-config`, `--model haiku` y
  `--max-turns 1`. Coste: **0,0099 USD** (una sola corrida).
- Ventana de prueba `w-20261022T051645Z` (05:16:45Z–05:26:51Z), abierta antes de la primera corrida
  y cerrada al final.
- Scripts y resultados en `evidence/F2-live/`.

## Resultados

### Sobrecarga de los hooks siempre declarados: CUMPLE

`run_overhead.ps1 -Repeat 3 -Calls 10` (P = con plugin, N = sin él; en los dos, solo el driver) y
`-Arms A,N -Sub overhead-on` (A = con plugin y la capa de lectura encendida). `analyze_overhead.py`
calcula el p95 por rango más cercano. Ficheros: `overhead-off-result.json` y `overhead-on-result.json`.

| Brazo | n en caliente | Mediana | p95 | Máx | Primera llamada (mediana, n=6) |
|---|---|---|---|---|---|
| Sin plugin (tanda 1) | 54 | 69 ms | 83 ms | 97 ms | 757,5 ms |
| Con plugin, capa de lectura apagada | 54 | 149 ms | 162 ms | 167 ms | 854,5 ms |
| **Diferencia** | | **+80 ms** (tope +150) | **+79 ms** (tope +300) | | +97 ms |
| Sin plugin (tanda 2) | 54 | 71 ms | 84 ms | 90 ms | 780 ms |
| Con plugin, capa de lectura encendida | 54 | 196,5 ms | 208 ms | 215 ms | 921,5 ms |
| **Diferencia** | | **+125,5 ms** (tope +150) | **+124 ms** (tope +300) | | +141,5 ms |

Tiempo del hook `shell` que anota el propio motor (`--debug-file`, 60 por tanda, todos con estado 0):
con la capa apagada, mediana 77 ms y p95 84 ms; encendida, mediana 123 ms y p95 131 ms. Las dos
configuraciones quedan dentro del tope; con la capa encendida el margen de la mediana es de 24,5 ms.

### REQ-003, latencia de cada hook: CUMPLE

`hook_latency.py <python del worktree> <work> 25`: 25 invocaciones de cada hook, lanzadas como las
lanza el motor (`-I -m local_delegate.hook <nombre>`, JSON por stdin), todas con código 0
(`hook-latency.json`).

| Hook | Capa de lectura | Mediana | p95 | Máx |
|---|---|---|---|---|
| `prompt` | — | 105,4 ms | 111,3 ms | 112,9 ms |
| `record-call` | — | 105,5 ms | 113,6 ms | 114,3 ms |
| `read` | apagada / encendida | 61,2 / 104,3 ms | 66,6 / 115,0 ms | 69,7 / 115,4 ms |
| `mcp-read` | apagada / encendida | 61,7 / 105,2 ms | 66,3 / 112,4 ms | 66,6 / 116,4 ms |
| `shell` | apagada / encendida | 61,6 / 105,3 ms | 70,7 / 110,7 ms | 100,9 / 111,0 ms |

Todas quedan muy por debajo de p95 ≤ 300 ms. En el motor, `UserPromptSubmit` tardó 123 ms y
`record-call` 121–122 ms, frente a 217–228 ms de los scripts de la entrega por settings de la 0.39
en el config real. Las 25 notas de prueba de `record-call` se borraron de
`%TEMP%\local-delegate-calls`.

### REQ-003, `ld_bin` roto: CUMPLE

`run_ldbin.ps1`: por caso, `claude -p "Reply with the single word OK." --output-format json` y
`claude -p "/f2bash 1"`, cada uno con su config aislado.

| `ld_bin` | `UserPromptSubmit` (motor) | Prompt | `PreToolUse:Bash` (motor) | `Bash` |
|---|---|---|---|---|
| python del worktree (control «pasa») | estado 0, 123 ms | llega a la API (`api_error`, «Not logged in») | estado 0, 77 ms | `stdout: f2` |
| `D:/does-not-exist/python.exe` | «failed to start» (3 ms) | **llega a la API** | «failed to start» (2 ms) | **`stdout: f2`** |
| python de la 0.39 instalada (`uv tool`) | estado 1, 1165 ms | **llega a la API** | estado 1, 744 ms | **`stdout: f2`** |
| control «bloquea»: `local-delegate.exe` de la 0.39 | estado 2 (argparse) | `num_turns: 0`, «blocked by hook» | estado 2 | `deny` |

El control positivo demuestra que el montaje sí puede dar «bloquea». Coste de bajar a la 0.39 sin
`uninstall`: unos 0,7–1,2 s por hook, con error no bloqueante (lo que la release debe avisar).

### REQ-016: CUMPLE

`run_req016.ps1`: `/f2mcp <tiny.txt>` (llamada a `local_summarize` por `$.tool.call`) y
`/local-summarize tiny.txt`.

| Caso | Mod | `record-call` (motor) | MCP | Fila del log de uso | `/local-summarize` |
|---|---|---|---|---|---|
| (a) todas las piezas a `off` (`pinned_tools: []`; `commands_enabled`, `status_enabled` y `read_mod_enabled` a `false`) | carga; latido con `pinned-tools: off` y `commands: off` (`status` y `read`, `absent`: aún no existen) | estado 0, 122 ms | devuelve el resumen | `toolu_plugin_202f…`, `caller_src: hook` | no existe: va al modelo («Not logged in») |
| (b) `register.js` con un `throw` en la primera línea | «hooks module did not load: Error: F2-live boom at load» | estado 0, 121 ms | devuelve el resumen | `toolu_plugin_54ca…`, `caller_src: hook` | no existe: va al modelo |

### REQ-015: CUMPLE

Sesión `3eda84c8-8f22-4553-b2fb-160474db1efd`, en el config real:

1. `claude -p "/local-summarize tiny.txt" --session-id <id> …` → `num_turns: 0`, coste 0, resumen.
2. `claude -p --resume <id> "Call the tool mcp__local-delegate__local_summarize once …" --model haiku …`
   → la tool corre y la sesión para por `max_turns` (lo esperado con `--max-turns 1`).

| Fila del log de uso | `tool_use_id` | `caller_src` | `caller_model` |
|---|---|---|---|
| 05:24:32Z, mod | `toolu_plugin_a793…` | `hook` | — |
| 05:24:52Z, modelo | `toolu_011x…` (está en el transcript de la sesión) | `hook+transcript` | `claude-haiku-5-5` |

`/api/stats` con el código de `main` (`TestClient(web.metrics.app)`, `from=05:24:00Z`,
`to=05:25:30Z`): con `include_tests=1`, `by_client[claude-code]` da `calls: 2` y **`mod_calls: 1`**,
y la raíz da `mod_calls: 1`; sin el interruptor, las dos filas salen como pruebas
(`excluded_tests: 2`). El daemon real es la 0.39 y su `/api/stats` aún no trae `mod_calls` (0
apariciones en `v0.39.0`): por eso se leyó con el código de `main` sobre el mismo log.
En el config real corrieron a la vez el `record-call` del plugin y el de la entrega por settings de
la 0.39 (doble entrega esperable antes de migrar; los dos escriben la misma nota).

### Puente del chat de Desktop: CUMPLE

`bridge_client.py D:\Projects\ld-wt-f2-live\.venv\Scripts\local-delegate.exe`: es el ejecutable de
consola del entorno del worktree, el mismo que lanza `uv run local-delegate`. Se lanza directamente,
sin `uv` delante, porque así lo hace Desktop. El entorno del hijo lleva solo las 30 variables de la
lista fija de r5 (`APPDATA` … `windir`, en `bridge-result.json`), ninguna `LOCAL_DELEGATE_*` y ningún
`env` en la entrada.

- `initialize`: sin error; `serverInfo` `local-delegate` 0.39.0 (el daemon real); protocolo 2025-06-18.
- `tools/list`: 11 tools (de `local_summarize` a `local_status`).
- `local_status`: `isError: false`, 1917 caracteres («local-delegate v0.39.0 …»).
- stderr: «puente de Claude Desktop hacia http://127.0.0.1:9393/mcp (token: presente)». El token salió
  de `HKCU\Environment`, no del entorno. Sale con 0 al cerrar stdin.
- El token no aparece en ninguna salida (`token_in_any_output: false`, comprobado contra el valor del
  registro sin imprimirlo).

### `process.run` en la pestaña Code de Desktop: PENDIENTE, tras instalar la 0.40.0

Necesita el plugin instalado de verdad y que el usuario abra una sesión en la pestaña Code. Antes,
hay que borrar los latidos de esta medición (ver «Restos»). Después se lee el latido más reciente:

```powershell
Get-ChildItem "$env:USERPROFILE\.claude\plugins\data\local-delegate-local-delegate\heartbeats\*.json" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3 |
  ForEach-Object { Get-Content $_ -Raw | ConvertFrom-Json | Select-Object session_id, entrypoint, process_run, pieces, at }
```

Cumple si la sesión de la pestaña Code (cuyo `entrypoint` no es `cli` ni `sdk-cli`) trae
`process_run: true`. De referencia, en `claude -p` el latido dio `entrypoint: sdk-cli` y
`process_run: true`.

## Configs reales antes y después

- `~/.claude/settings.json`: idéntico byte a byte.
- `claude plugin list --json`: idéntico (el plugin no quedó instalado).
- `~/.claude.json`: `mcpServers` idéntico y ningún proyecto nuevo. Solo cambian claves que el CLI
  reescribe en cada arranque (cachés de experimentos, `promptQueueUseCount`…) y `pluginUsage`, donde
  el motor añadió `local-delegate@inline` (`usageCount: 3`) por las tres corridas con `--plugin-dir`
  en el config real.

## Restos en el `~/.claude` real (no los borré: el clasificador del modo automático denegó el `rm`)

- `~/.claude/plugins/data/local-delegate-local-delegate/heartbeats/3eda84c8-….json` (el latido de la
  sesión de REQ-015) y la carpeta vacía `~/.claude/plugins/data/local-delegate-inline/`. No existían
  antes. Hay que borrarlas antes de medir `process.run`; si no, `doctor` y la lectura del latido verán
  una sesión `sdk-cli` que no es de Desktop.
- `pluginUsage["local-delegate@inline"]` en `~/.claude.json` (un contador del motor; no se toca a mano).
- Los transcripts de las dos corridas de REQ-015, en `~/.claude/projects/<carpeta de trabajo del
  scratchpad>/`.
- En la ventana `w-20261022T051645Z` cayó una fila ajena (05:17:36Z, `local_commit_msg` de un
  subagente de otro lote), que queda marcada como prueba. Las 4 filas propias son las de REQ-015 y
  REQ-016.

## Llamadas `local_*`

- `local_summarize` ×3 (`path`): `F1-desktop-bridge.md`, `F2-mod-core.md` y `F2-attribution.md`.
- `local_extract` ×1 (`path`): `T0.md` (salió truncada; las líneas concretas las leí con `grep`).
- `local_explain_code` ×1 (`path`): `english-names-bilingual-output/evidence/B2d-2/run_live.py`.
- `local_commit_msg` ×1 (`path`, con el diff volcado): borrador del commit.
- `local_lint_summary`: 0, porque este lote no cambia código y no corre pytest.
