# R1 — El formato de plugin de Claude Code como vía de distribución de local-delegate

Fecha: 2026-10-21 · Claude Code **2.1.306** (Windows 11) · Investigación, sin cambios en el repo.

Marcas: **[PRUEBA]** comprobado en esta PC con un plugin desechable; **[DOC]** doc oficial
(`code.claude.com/docs/en/plugins/*`, descargada hoy en Markdown); **[3º]** repos de terceros u
oficiales de ejemplo. Lo que es inferencia mía va como «Inferencia».

Banco de pruebas: plugin `ld-r1-probe` + marketplace local `ld-r1-mkt` en
`C:/Users/Yohan/AppData/Local/Temp/claude/D--Projects-local-delegate/ed2ae533-e76e-4dce-ae5d-1dd44f83b27e/scratchpad/r1/mkt/`,
todo con `CLAUDE_CONFIG_DIR` apuntando a `…/scratchpad/r1/home-cfg` (nunca se tocó `~/.claude`), un
oyente HTTP en `127.0.0.1:18765` que solo registraba la cabecera `Authorization` (tokens ficticios).
Las sesiones `claude -p` se lanzaron **sin sesión iniciada**: los hooks `SessionStart` se disparan y
luego sale «Not logged in», así que **no se gastó ningún turno de modelo**.

---

## Conclusiones para el diseño (lo esencial)

1. **El servidor MCP HTTP del daemon cabe tal cual en el `.mcp.json` del plugin**, con
   `"Authorization": "Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"`: la variable se expande (no está en la
   lista de credenciales que Claude Code vacía) [PRUEBA]. Alternativa sin variable de entorno: un
   `userConfig` `sensitive` (`${user_config.web_token}`), que Claude Code guarda en su almacén seguro
   (en Windows, `.credentials.json` → `pluginSecrets`) [PRUEBA].
2. **Cambian los nombres de las tools**: dentro de un plugin pasan de `mcp__local-delegate__local_x`
   a `mcp__plugin_<plugin>_<servidor>__local_x` [DOC]. Eso rompe matchers de hooks
   (`mcp__local-delegate__.*`), permisos (`mcp__local-delegate__*`), listas `tools:` de los agentes,
   el `ToolSearch("select:…")` del bloque gestionado de `CLAUDE.md` y cualquier conteo del panel por
   nombre de tool. Es el mayor coste de la migración.
3. **Si el MCP de usuario y el del plugin apuntan a la misma URL, gana el de usuario y el del plugin
   se descarta** (no hay tools duplicadas) [PRUEBA + DOC]. Sirve para una migración por fases.
4. **Un hook idéntico en `settings.json` y en el plugin se dispara DOS veces** [PRUEBA + DOC]. La
   migración tiene que quitar los hooks de `settings.json` en el mismo paso en que activa el plugin
   (y `doctor` debe detectar la duplicación).
5. **`claude plugin marketplace add` + `claude plugin install --config … --json` funcionan sin
   interacción** y devuelven JSON parseable; `claude plugin configure --values-stdin` fija opciones
   (incluidas las sensibles) sin que pasen por la línea de comandos [PRUEBA]. `local-delegate install`
   puede hacerlo todo.
6. **Hooks en Windows**: la forma exec (`command` + `args`) resuelve nombres sueltos en el `PATH`:
   `"command": "local-delegate"` ejecutó el trampolín `.exe` de `uv tool` (1,1 s) y `"command":
   "python"` también [PRUEBA]. En macOS no se pudo probar; `python` no existe por defecto allí
   (Inferencia + [3º]).
7. **Claude Desktop**: la pestaña **Code** y la extensión de VS Code leen los mismos ficheros de
   settings que la CLI, así que un plugin instalado a nivel usuario sirve en los tres [DOC]. El
   **chat** de Desktop ignora hooks y MCP locales [DOC]; Cowork sí los carga en la máquina local
   [DOC]. El plugin **no sustituye** a `claude_desktop_config.json` para el chat.
8. **CI sin cuenta es viable**: `claude plugin validate --strict --json` no necesita sesión [PRUEBA],
   y `claude -p` sin credenciales sigue disparando los hooks `SessionStart` antes de salir con
   «Not logged in» [PRUEBA], lo que permite una prueba de humo de carga y entorno de hooks a coste cero.

---

## 1. Anatomía de un plugin

### 1.1 Estructura y manifiesto

- El manifiesto `.claude-plugin/plugin.json` es **opcional**; sin él se cargan los componentes de la
  estructura estándar. Todo lo demás va en la raíz del plugin, no dentro de `.claude-plugin/` [DOC]
  ([manifest-reference](https://code.claude.com/docs/en/plugins/manifest-reference)).
- Ubicaciones por defecto [DOC]: `skills/<n>/SKILL.md`, `commands/*.md` (se recomienda pasar a
  skills), `agents/*.md`, `hooks/hooks.json`, `.mcp.json`, `.lsp.json`, `output-styles/`,
  `workflows/`, `themes/`, `monitors/monitors.json`, `bin/` (va al `PATH` de la tool Bash),
  `settings.json` (solo `agent` y `subagentStatusLine`).
- Campos principales [DOC]: `name` (único obligatorio, kebab-case, espacio de nombres de todo),
  `displayName`, `version`, `description`, `author`, `homepage`, `repository`, `license`,
  `keywords`, `defaultEnabled` (por defecto `true`), `dependencies`, `settings`, `userConfig`,
  `types` (para mods), `channels`, y las claves de componentes `skills`, `commands`, `agents`,
  `hooks`, `mcpServers`, `lspServers`, `outputStyles`, `workflows`, `experimental.{themes,monitors,evals}`.
- Rutas: relativas a la raíz y con `./`; las que salen de la raíz (`..`, symlinks hacia fuera) no
  cargan; en macOS/Linux una ruta con `\` se rechaza [DOC].
- `commands`, `agents`, `outputStyles`, `workflows` **reemplazan** la carpeta por defecto; `skills`
  **suma**; `hooks`, `mcpServers`, `lspServers` **se fusionan** con el fichero por defecto [DOC].
- Nombres reservados: no puede empezar por `claude-`, `anthropic-`, `cc-plugin-`, etc.; `claude`
  como palabra suelta da aviso [DOC]. `local-delegate` está libre.
- Un `CLAUDE.md` en la raíz del plugin **no** se carga como contexto; las instrucciones van en una
  skill [DOC].
- `version`: cadena libre. **Si se fija, los usuarios se quedan en esa versión hasta que cambie**;
  sin `version`, la versión es el SHA del commit (fuentes git) [DOC]
  ([loading](https://code.claude.com/docs/en/plugins/loading#versions-and-updates)).

### 1.2 `userConfig`

- Cada opción: `type` (`string|number|boolean|directory|file`), `title`, `description`,
  `required`, `default`, `options` (≥ 2.1.271), `multiple`, `sensitive`, `min/max`. Objeto estricto:
  una clave desconocida impide cargar el plugin [DOC].
- No sensibles → `pluginConfigs` en `settings.json`; sensibles → almacén seguro [DOC]. Comprobado en
  Windows: la no sensible quedó en `settings.json` → `pluginConfigs.<id>.options`, la sensible en
  `.credentials.json` → `pluginSecrets` del directorio de configuración [PRUEBA].
- Uso: `${user_config.KEY}` en config MCP/LSP, `args` de hooks en forma exec y contenido de skills y
  agentes (las sensibles no se sustituyen en skills/agentes); y `CLAUDE_PLUGIN_OPTION_<KEY>` en el
  entorno de todos los hooks [DOC]. Comprobado: `args` recibió el valor de `dashboard_url`, y el hook
  recibió `CLAUDE_PLUGIN_OPTION_WEB_TOKEN` (la sensible) y `CLAUDE_PLUGIN_OPTION_DASHBOARD_URL`
  [PRUEBA].
- Los hooks en forma shell, los monitores y `headersHelper` **rechazan** `${user_config.*}` [DOC].
- El diálogo de configuración solo existe en `/plugin` interactivo y en VS Code; `claude plugin
  install` nunca pregunta: usa `--config KEY=VALUE` o `claude plugin configure --values-stdin`
  [DOC + PRUEBA].

### 1.3 `.mcp.json` del plugin

- Mismo formato que un `.mcp.json` de proyecto, con o sin envoltorio `mcpServers` [DOC]
  ([components#mcp-servers](https://code.claude.com/docs/en/plugins/components#mcp-servers)).
- Transportes: stdio, http, sse, ws [DOC]. En http/sse/ws se sustituyen `${…}` en `url`, `headers`
  y `headersHelper`; en stdio, en `command`, `args`, `env` [DOC].
- **Cabecera con variable de entorno**: probado con tres servidores contra el oyente local [PRUEBA]:

  | Config | Cabecera recibida |
  | :- | :- |
  | `"Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"` (variable puesta a `dummy-a-123`) | `Bearer dummy-a-123` |
  | `"Bearer ${LD_R1_SECRET:-fallback-b}"` (variable sin definir) | `Bearer fallback-b` |
  | `"Bearer ${user_config.web_token}"` antes / después de `configure` | `Bearer` / `Bearer dummy-c-789` |
  | `"X-Root": "${CLAUDE_PLUGIN_ROOT}"` | ruta absoluta con `/` |
  | `"url": "${user_config.dashboard_url}/c/mcp"` | sustituida por el `default` |

- Ojo: Claude Code **vacía** en `url`/`headers` remotos ciertas variables de credenciales
  (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `AWS_BEARER_TOKEN_BEDROCK`, `HTTPS_PROXY`,
  `NPM_TOKEN`…) [DOC] ([mcp#credential-variables-that-read-as-empty](https://code.claude.com/docs/en/mcp#credential-variables-that-read-as-empty)).
  `LOCAL_DELEGATE_WEB_TOKEN` no está en esa lista [PRUEBA].
- Variable sin definir y sin `:-default`: el servidor carga con el texto `${VAR}` literal y avisa en
  `claude mcp list` [DOC] → el daemon recibiría `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}` y daría 401.
- Nombres: servidor `plugin:<plugin>:<servidor>` (visto en `claude mcp list` [PRUEBA]); tools
  `mcp__plugin_<plugin>_<servidor>__<tool>`; un matcher con el nombre corto **nunca** se dispara
  [DOC] ([mcp#plugin-provided-mcp-servers](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers)).
  Con plugin `local-delegate` y servidor `local-delegate`:
  `mcp__plugin_local-delegate_local-delegate__local_summarize`.
- Precedencia: local > proyecto > usuario > **plugin** > conectores de claude.ai; los plugins se
  comparan **por endpoint** (misma URL o comando = duplicado) [DOC]
  ([mcp#scope-hierarchy-and-precedence](https://code.claude.com/docs/en/mcp#scope-hierarchy-and-precedence)).
  Comprobado: con un MCP de usuario a la misma URL, el `probe-a` del plugin desapareció de `claude mcp
  list` y solo llegó la cabecera del de usuario [PRUEBA].
- Un servidor remoto ya usado puede salir como `cached` y conectarse al primer uso [DOC].
- `claude mcp get` oculta los valores de un servidor stdio/ws de plugin [DOC].
- Desde 2.1.281, `claude plugin validate` revisa también el `.mcp.json`: entradas que se
  descartarían, `${user_config.KEY}` no declarado, URL no absoluta (errores); `http://` a host no
  loopback y cabeceras que parecen credenciales literales (avisos) [DOC]. Con `http://127.0.0.1` no
  avisó [PRUEBA].

### 1.4 `hooks/hooks.json`

- Mismo formato que `hooks` de `settings.json`, envuelto en `{"hooks": {…}}`; un fichero sin el
  envoltorio no carga [DOC]. Eventos y campos idénticos a los de settings (PreToolUse, PostToolUse,
  UserPromptSubmit, SessionStart, Stop…) [DOC] ([hooks](https://code.claude.com/docs/en/hooks)).
- Se registran al cargar el plugin y se disparan siempre, no esperan a que se use una skill [DOC].
  También se disparan dentro de subagentes [DOC].
- **Forma exec** (con `args`): sin shell, `command` se resuelve en el `PATH`; en Windows tiene que
  ser un ejecutable real (`.exe`), no un `.cmd/.bat` [DOC]. **Forma shell** (sin `args`): `sh -c`
  en macOS/Linux, Git Bash en Windows (PowerShell si no hay Git Bash, o `"shell": "powershell"`)
  [DOC].
- Entorno de cada hook de plugin: `CLAUDE_PLUGIN_ROOT`, `CLAUDE_PLUGIN_DATA`, `CLAUDE_PROJECT_DIR`,
  `CLAUDE_PLUGIN_OPTION_<KEY>` [DOC + PRUEBA], además del entorno heredado (llegaron
  `LOCAL_DELEGATE_WEB_TOKEN`, `LOCAL_DELEGATE_AUTOSTART`, `CLAUDECODE=1`) [PRUEBA].
- Barras en Windows [PRUEBA]: en forma shell `${CLAUDE_PLUGIN_ROOT}` se sustituyó con `/`; **en forma
  exec el `args` recibió la ruta con `\`** seguida de `/scripts/probe.py` (mezcla, pero Python la
  abrió bien), y la variable de entorno `CLAUDE_PLUGIN_ROOT` llegó con `\` en el hook exec y con `/`
  en el shell. La doc dice «forward slashes» en general; el código del hook no debe suponer un
  separador.
- **Cómo invocar local-delegate**:
  - Windows: `~/.local/bin/local-delegate.exe` es un PE32+ real (trampolín de `uv`) →
    `{"type":"command","command":"local-delegate","args":[…]}` funciona en forma exec [PRUEBA]
    (salida «local-delegate 0.39.0» en el log de depuración, 1127 ms).
  - macOS: la misma forma exec debería funcionar si `~/.local/bin` está en el `PATH` del proceso de
    Claude Code (Inferencia). Riesgo: lanzado desde una app gráfica (Desktop) el `PATH` puede no
    incluirlo. Mitigación posible: ruta absoluta en un `userConfig` (`"command":
    "${user_config.ld_bin}"`, permitido en forma exec [DOC]) que `local-delegate install` rellena con
    `--config`.
  - Hoy los hooks son scripts `python "<ruta>"` (ver `~/.claude/settings.json`). Con `python` suelto:
    en Windows funcionó [PRUEBA]; en macOS no existe `python` por defecto, y en Windows `python3` puede
    ser el stub de la Microsoft Store que sale con 49 en silencio [3º] (comentario de
    `security-guidance/hooks/sg-python.sh` en
    [claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/security-guidance/hooks)).
    Recomendación: exponer cada hook como subcomando de la CLI (`local-delegate hook <nombre>`) y
    llamarlo en forma exec; así no hay que resolver el intérprete (Inferencia).
- Coexistencia con `settings.json`: «Si defines el mismo handler en más de un fichero de settings, se
  ejecuta una vez. La copia de un plugin o de una skill queda aparte» [DOC]
  ([hooks](https://code.claude.com/docs/en/hooks), sección de tipos de hook). Comprobado: el mismo
  `python ".../probe.py" dup` en settings y en el plugin escribió dos líneas (una sin
  `CLAUDE_PLUGIN_*`, otra con ellas) [PRUEBA].
- `disableAllHooks: true` apaga también los hooks de plugins (con `--settings <fichero>` no corrió
  ninguno) [PRUEBA]; no apaga los gestionados salvo que esté en managed settings [DOC].
- `allowManagedHooksOnly` (managed): bloquea los hooks de usuario, proyecto, local **y de plugins**,
  salvo plugins forzados en `enabledPlugins` gestionado [DOC]. Si alguien lo usa, el plugin pierde los
  hooks igual que hoy los pierde la instalación por settings.
- Si dos plugins habilitados comparten nombre, solo uno registra sus hooks [DOC].

### 1.5 Skills, agentes y comandos

- Se espacian con el nombre del plugin: skill `/local-delegate:resumir`, agente
  `local-delegate:<nombre>` [DOC]. `claude plugin details` listó `r1-hello`, `r1cmd` (los comandos
  cuentan como skills), `r1-agent`, hooks y MCP, con coste estimado de ~44 tokens fijos [PRUEBA].
- En agentes de plugin se **ignoran** `permissionMode`, `hooks`, `mcpServers`, `initialPrompt` [DOC]
  ([components#frontmatter-fields-in-plugin-agents](https://code.claude.com/docs/en/plugins/components#frontmatter-fields-in-plugin-agents)).
  Sus `tools:` deben usar el nombre largo de las tools de plugin.
- `${CLAUDE_PLUGIN_ROOT}` se sustituye en el cuerpo de skills/comandos/agentes, pero esas variables
  **no** están en el entorno de la tool Bash [DOC].

### 1.6 Mods (módulos de hooks)

- Un mod es un plugin cuyo `hooks/hooks.json` tiene `"modules": ["./register.js"]` (una sola ruta);
  puede convivir con hooks de settings en el mismo fichero [DOC]
  ([mods/reference#files](https://code.claude.com/docs/en/plugins/mods/reference#files)).
- `register(on, options)` recibe los `userConfig` con sus valores por defecto [DOC].
- Requisitos: CLI ≥ 2.1.287; Desktop ≥ 2.1.286; extensión de VS Code ≥ 2.1.299 para dibujar [DOC]
  ([mods/overview](https://code.claude.com/docs/en/plugins/mods/overview)). En `claude -p` corren los
  hooks pero no se dibuja nada [DOC].
- Ya hay mods integrados cargados como plugins `@builtin` (`cc-plugin-agents-md`,
  `cc-plugin-telemetry`, `cc-plugin-plugin-authoring`) [PRUEBA, log de depuración].

## 2. Distribución

- **Marketplace en el mismo repo**: soportado. Se pone `.claude-plugin/marketplace.json` en la raíz
  del repo; la entrada puede apuntar a `"./"` o a un subdirectorio [DOC]
  ([publish](https://code.claude.com/docs/en/plugins/publish#add-the-marketplace-file-to-your-repository),
  [marketplace-reference](https://code.claude.com/docs/en/plugins/marketplace-reference)).
  Para este repo conviene un subdirectorio (p. ej. `./plugins/local-delegate`): con `"./"` se copiaría
  todo el repo (src, tests, docs…) a la caché de cada usuario (Inferencia a partir de [DOC]: se copia
  el directorio del plugin entero). Es el patrón de `openai/codex-plugin-cc` [3º].
  `claude plugin validate .` en la raíz valida marketplace y plugin si ambos están ahí (≥ 2.1.289) [DOC].
- `marketplace.json`: `name`, `owner`, `plugins` obligatorios; `name` no puede imitar uno oficial ni
  ser `npm/pip/uv/github/gh`… [DOC]. Probado `ld-r1-mkt` con fuente relativa: válido [PRUEBA].
- Comandos (todos no interactivos, salida `--json` con `outcome`):
  - `claude plugin marketplace add ZahiriNatZuke/local-delegate[#ref]` [DOC]; con ruta local
    probado [PRUEBA].
  - `claude plugin install local-delegate@<mkt> [--scope user|project|local] [--config K=V]`
    [DOC + PRUEBA]; atajo `--marketplace <source>` que añade el marketplace y lo instala (≥ 2.1.292)
    [DOC]. Sin TTY solo se niega si la fuente es de tipo `command` o lleva `headersHelper` (no es
    nuestro caso) [DOC].
  - `claude plugin configure <id> --values-stdin` / `--json` [PRUEBA].
  - `claude plugin update <id>`, `enable`, `disable`, `uninstall [--keep-data]`, `list --json`,
    `details` [DOC + PRUEBA para update/enable/disable/list/details].
  - `claude plugin tag [path] [--push] [--dry-run]` crea la etiqueta `<name>--v<version>` y comprueba
    que `plugin.json` y la entrada del marketplace coinciden [DOC].
- **Actualización** [DOC + PRUEBA]: cada versión va a `plugins/cache/<mkt>/<plugin>/<version>/`;
  `update` instala la nueva al lado y marca la vieja con `.orphaned_at` (visto en la prueba de
  0.0.1 → 0.0.2); la vieja se borra 14 días después, así que las sesiones abiertas siguen con la
  suya. La sesión abierta no cambia hasta `/reload-plugins` o reinicio. Es atómico en la práctica
  (directorio nuevo, no sobrescritura).
- El auto-update está **apagado por defecto** para marketplaces de terceros; lo activa el usuario o
  `extraKnownMarketplaces.<mkt>.autoUpdate` [DOC]. Con `version` fijada, publicar commits no actualiza
  nada hasta subir la versión [DOC].
- Marketplace añadido desde **ruta local**: el plugin se carga **en sitio** (desde la fuente), aunque
  `list` muestre una copia en caché; los cambios entran en la siguiente sesión sin cambiar versión
  [DOC + PRUEBA: el log leía `hooks.json` desde `mkt/plugins/…` tras el `update`].
- **Zip**: `--plugin-dir x.zip` y `--plugin-url` cargan un zip solo para esa sesión [DOC + PRUEBA].
  Un fichero `.plugin` **no** se descomprime por `--plugin-dir`: lo dio por «loaded» con el nombre del
  fichero y sin manifiesto [PRUEBA]. El `.plugin`/zip es el formato de **subida** de claude.ai/Cowork
  («Upload plugin») [DOC claude.com].
- Otra vía sin marketplace: una carpeta con `.claude-plugin/plugin.json` dentro de `~/.claude/skills/`
  se carga en todas las sesiones como `<name>@skills-dir`, sin instalar [DOC]
  ([create](https://code.claude.com/docs/en/plugins/create)). Pierde actualizaciones gestionadas por
  Claude Code y queda por debajo de un plugin de marketplace en precedencia [DOC].
- `<claude-code-hint>` para que la CLI recomiende el plugin: solo para plugins de marketplaces con
  nombre oficial [DOC] ([cli-hints](https://code.claude.com/docs/en/plugins/cli-hints)). No aplica.
- La doc recomienda exactamente nuestro caso: «si mantienes una CLI, que tu instalador ejecute
  `claude plugin marketplace add <source>` y `claude plugin install <name>@<marketplace>`» [DOC]
  ([publish#ship-a-plugin-with-your-own-tool](https://code.claude.com/docs/en/plugins/publish#ship-a-plugin-with-your-own-tool)).

## 3. Ámbitos, almacenamiento y activación

- Ámbitos: `user` (`~/.claude/settings.json`), `project` (`.claude/settings.json`), `local`
  (`.claude/settings.local.json`); se registra en `enabledPlugins` [DOC + PRUEBA:
  `"enabledPlugins": {"ld-r1-probe@ld-r1-mkt": true}` y el marketplace en `extraKnownMarketplaces`].
  Precedencia `--add-dir` < user < project < local < `--settings` < managed [DOC].
- Raíz de plugins: `~/.claude/plugins` (o `CLAUDE_CODE_PLUGIN_CACHE_DIR`; con `CLAUDE_CONFIG_DIR`
  se mueve con él [PRUEBA]). Dentro: `cache/`, `data/<id>/` (`${CLAUDE_PLUGIN_DATA}`, sobrevive a
  updates, se borra al desinstalar salvo `--keep-data`), `marketplaces/`, `installed_plugins.json`,
  `known_marketplaces.json` [DOC + PRUEBA].
- `CLAUDE_PLUGIN_DATA` se crea aunque el hook no la use (bastó con exportarla al hook) [PRUEBA]; en
  esta PC ya existen carpetas así de otras pruebas (`warp-inline`).
- `claude plugin disable` → `enabledPlugins.<id>: false`; en la siguiente sesión ya no corrió ningún
  hook del plugin [PRUEBA]. En `/mcp` se puede apagar solo el servidor del plugin [DOC].
- Doble disparo y `disableAllHooks`/`allowManagedHooksOnly`: ver §1.4.

## 4. Plataformas y versiones

- Windows: todo lo de este informe se probó aquí [PRUEBA]. macOS: sin probar; riesgos conocidos:
  rutas con `\` rechazadas, `python` inexistente, `PATH` de app gráfica (Inferencia + [DOC]).
- Claude Desktop, pestaña Code: instala desde «+ → Add plugins», comparte settings con CLI y VS Code;
  no hay plugins en sesiones WSL [DOC]
  ([install](https://code.claude.com/docs/en/plugins/install), [mods/overview](https://code.claude.com/docs/en/plugins/mods/overview)).
- VS Code: diálogo «Manage plugins», pide los `userConfig` sin valor [DOC].
- Chat de claude.ai / Desktop: carga skills y comandos, **ignora** agentes, hooks, MCP locales y los
  MCP con `${user_config}` en la URL; Cowork carga hooks y MCP locales si corre en tu máquina, pero no
  pide valores de `userConfig` (ignora MCP cuya opción no tenga default); un `bin/` de primer nivel
  impide instalar en chat/Cowork [DOC] ([platform-support](https://claude.com/docs/plugins/platform-support)).
  → No poner `bin/` en la raíz del plugin.
- Versiones mínimas que importan [DOC]: validación MCP en `validate` 2.1.281; `CLAUDE_CODE_PLUGIN_DIRS`
  2.1.280; `install --json` 2.1.268; `install --marketplace` 2.1.292; `update` sin `--scope` correcto
  2.1.281; `onFailure` en hooks 2.1.295; mods 2.1.287 (Desktop 2.1.286, VS Code 2.1.299);
  `userConfig.options` 2.1.271 (si se usa, versiones anteriores **no cargan** el plugin). Propuesta:
  exigir ≥ 2.1.292 y comprobarlo en `doctor` (Inferencia).

## 5. Ejemplos reales

- [`openai/codex-plugin-cc`](https://github.com/openai/codex-plugin-cc) [3º]: marketplace
  `openai-codex` en el mismo repo, plugin en `./plugins/codex` con `version` fijada (1.0.6) en
  manifiesto y entrada; 8 comandos (`/codex:review`, `/codex:setup`…), 1 agente, 3 skills y hooks
  `SessionStart`/`SessionEnd`/`Stop` en forma shell `node "${CLAUDE_PLUGIN_ROOT}/scripts/…"`. **Sin
  MCP**: envuelve una CLI instalada aparte (`codex`), igual que local-delegate con `uv tool`.
- [`anthropics/claude-plugins-official`](https://github.com/anthropics/claude-plugins-official) [3º]:
  ningún plugin oficial combina MCP + hooks. Útiles: `external_plugins/github/.mcp.json` (HTTP con
  `"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"`, el mismo patrón que el nuestro);
  `external_plugins/serena/.mcp.json` (stdio con `uvx`); `plugins/hookify` (hooks `python3 "…"` en
  4 eventos); `plugins/security-guidance` (lanzador `sg-python.sh` que prueba `python3`, `python`,
  `py -3` y fuerza `PYTHONUTF8=1` por el cp1252 de Windows; usa `asyncRewake` e `if`).
- Mods de muestra en [`anthropics/claude-code-playground/claude-code/mods`](https://github.com/anthropics/claude-code-playground/tree/main/claude-code/mods)
  (`blast-radius`, `token-weather`, `replay-theater`) [DOC].

## 6. Pruebas y CI

- `claude plugin validate <dir> [--strict] [--json]`: códigos 0/1/2; `--strict` convierte avisos en
  error; sin sesión iniciada [PRUEBA]. Además corre comprobaciones del directorio de Anthropic
  (README, LICENSE, icono, `privacyPolicyUrl` si hay MCP remoto) que no cambian el resultado salvo
  con `--profile directory` [PRUEBA].
- `claude plugin test [dir]`: solo para mods (`*.test.ts[x]`), sin sesión ni red [DOC]; el brief ya
  advierte que no imita bien al motor.
- `--plugin-dir <dir|zip>` (repetible) o `CLAUDE_CODE_PLUGIN_DIRS` (≥ 2.1.280, `;` en Windows) cargan
  el plugin solo para esa sesión; un plugin de sesión **sustituye** en silencio al instalado con el
  mismo nombre [DOC]. `claude --plugin-dir X plugin list` y `claude --plugin-dir X mcp list` lo
  muestran [PRUEBA].
- **CI sin cuenta** [PRUEBA]: con `CLAUDE_CONFIG_DIR` vacío y sin credenciales:
  1. `claude plugin validate --strict --json` del marketplace y del plugin;
  2. `claude plugin marketplace add <checkout>` + `claude plugin install … --json` (instalación real
     en el HOME simulado);
  3. `claude mcp list` contra un oyente falso → comprueba nombres `plugin:…` y la cabecera que llega;
  4. `claude -p x --max-turns 1` → los hooks `SessionStart` corren antes del «Not logged in» (exit 1
     esperado): sirve para comprobar que el comando del hook resuelve y su entorno.
  Los hooks de herramienta (PreToolUse, etc.) no se pueden disparar sin modelo; eso queda para la
  prueba en vivo con ventana de prueba. En CI, `CLAUDE_CODE_SYNC_PLUGIN_INSTALL=1` y `--output-format
  stream-json --verbose` (evento `init` → `plugins`) ayudan con `-p` [DOC]
  ([org#seed-containers-and-ci](https://code.claude.com/docs/en/plugins/org#seed-containers-and-ci)).

## Riesgos y preguntas abiertas

1. Renombrado de tools (§1.3): decidir si el plugin trae el MCP o si se deja el MCP de usuario
   (gana por URL) y el plugin solo aporta hooks, skills, agentes y mod. Lo segundo evita el renombrado.
2. Token en macOS con Desktop: `${LOCAL_DELEGATE_WEB_TOKEN}` depende del entorno del proceso; un
   `userConfig` sensible no depende de él, pero obliga a guardarlo (choca con «el token nunca se
   escribe» del brief). Hay que decidir.
3. Doble disparo durante la migración: `install` tiene que quitar los hooks de settings y activar el
   plugin a la vez; `doctor` tiene que detectar las dos cosas a la vez.
4. Comportamiento en macOS sin probar (`PATH`, `python`).
5. `version` fija frente a SHA: con versión fija, `local-delegate update` debe ejecutar `claude plugin
   marketplace update` + `claude plugin update` (el auto-update de terceros viene apagado).
