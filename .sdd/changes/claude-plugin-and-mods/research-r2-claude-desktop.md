# R2 — Claude Desktop como destino del plugin de local-delegate

Fecha: 2026-10-21. Solo lectura sobre `%APPDATA%\Claude`, `%LOCALAPPDATA%\Claude`, `~/.claude` y la
config real; Desktop no se abrió, no se reinició ni se editó. Etiquetas: **[PRUEBA]** medido en esta
PC, **[DOC]** doc oficial de Anthropic leída hoy, **[3º]** fuente de terceros, **[INF]** inferencia
mía, marcada como tal.

## 0. Lo esencial en seis líneas

1. Desktop son **dos productos con dos registros**: la pestaña Code es Claude Code (lee `~/.claude`,
   carga plugins, hooks, mods y skills de la CLI); el chat (y Cowork) lee la cuenta de claude.ai y
   `claude_desktop_config.json`/extensiones `.mcpb`, y **no** ve plugins, hooks ni mods locales.
2. El plugin de Claude Code **llega solo a la pestaña Code** con un `claude plugin install` a nivel
   usuario: no hace falta nada específico de Desktop para esa cara.
3. Para el chat, la vía de un MCP local es stdio: o la entrada en `claude_desktop_config.json` (la de
   hoy, vía `mcp-remote`) o una extensión `.mcpb`, que **no se puede instalar sin un clic** del usuario.
4. **Trampa nueva**: la entrada `local-delegate` de `claude_desktop_config.json` **también se carga en
   la pestaña Code** y, a igual nombre, gana sobre `~/.claude.json`. Con el plugin, la pestaña Code
   tendría el servidor dos veces (nombres distintos) y las tools duplicadas.
5. `${VAR}`: Desktop no documenta expandirlo, pero no hace falta: `mcp-remote` lo sustituye desde su
   propio entorno. Falta medir que el hijo herede la variable de usuario; dejo un sondeo de solo
   lectura que lo mide **sin reiniciar Desktop** la próxima vez que esté abierto.
6. Skills del chat: salen de la cuenta de claude.ai (el «registro aparte» es una caché que la app
   regenera). Sin API documentada para instalarlas por programa: se suben a mano en claude.ai.

## 1. Qué ve cada cara de Desktop

### 1.1 Pestaña Code

- Es Claude Code con interfaz gráfica: «Desktop runs the same underlying engine» y «Desktop and CLI
  read the same configuration files»: CLAUDE.md, MCP de `~/.claude.json`/`.mcp.json`, hooks y skills
  de settings, `~/.claude/settings.json` (permisos incluidos). **[DOC]**
  [desktop#shared-configuration](https://code.claude.com/docs/en/desktop) (sección «Coming from the CLI?»).
- Plugins: «The terminal, the desktop app's local sessions, and the VS Code extension on one computer
  read the same settings files, so a plugin you install at user scope in any of them is available in
  the other two». **[DOC]** [plugins/install#choose-an-install-scope](https://code.claude.com/docs/en/plugins/install).
- Mods: corren en la pestaña Code (hooks sí; lo que dibujan, sí, salvo elementos marcados
  «terminal-only»), desde Claude Code 2.1.286 en Desktop. **[DOC]**
  [plugins/mods#where-mods-run](https://code.claude.com/docs/en/plugins/mods).
- Versión de la copia propia de la pestaña Code en esta PC: carpetas `2.1.288` y `2.1.304` en
  `%APPDATA%\Claude\claude-code\` (la CLI va por 2.1.306). La pestaña Code trae su propia copia y se
  actualiza con Desktop, no con la CLI. **[PRUEBA]** + **[DOC]** (desktop, «Claude Code version in the Code tab»).
- Skills: las sesiones locales cargan `~/.claude/skills/` **y** las habilitadas en la cuenta de
  claude.ai. **[DOC]** (desktop, «Use skills»).
- Variables de entorno: «On Windows, the app inherits user and system environment variables but does
  not read PowerShell profiles»; `env` de `~/.claude/settings.json` también vale para sesiones
  locales. **[DOC]** (desktop, «Set environment variables for local sessions»).
- **MCP de `claude_desktop_config.json` dentro de la pestaña Code**: «A server you define in
  `claude_desktop_config.json` is available in both the Desktop chat surface and local Code tab
  sessions. If you define the same server name in `claude_desktop_config.json` and in `~/.claude.json`
  or `.mcp.json`, the Code tab in local sessions connects once and uses the
  `claude_desktop_config.json` definition». **[DOC]** (desktop, «MCP servers from the Claude Desktop chat app»).
  → Hoy, en la pestaña Code, `local-delegate` es **la entrada de Desktop** (npx + `mcp-remote@latest`
  + token literal), no la HTTP con `${LOCAL_DELEGATE_WEB_TOKEN}` de `~/.claude.json`. **[INF]** a partir de
  la doc y de la config leída.
- Plugins de la cuenta de claude.ai llegan a Claude Code como `<name>@synced`. **[DOC]** (plugins/install).

### 1.2 Sesiones WSL de la pestaña Code

- «Plugins aren't available in WSL sessions»; por tanto tampoco mods. Conectores pueden faltar. Lo
  que corre en la distro usa el `~/.claude` de Linux. **[DOC]**
  [desktop-wsl](https://code.claude.com/docs/en/desktop-wsl), [mods#where-mods-run](https://code.claude.com/docs/en/plugins/mods).
  → Para local-delegate: en WSL solo funcionaría lo que `install` ya escribe dentro de la distro, no el plugin.

### 1.3 Chat (y Cowork)

- Tabla oficial de componentes de plugin por superficie (Chat = claude.ai web, **app de escritorio** y
  móvil): skills **sí**; comandos como skill; agentes **ignorados**; hooks **ignorados**; MCP remoto
  `http/sse` solo vía pestaña «Connectors»; **MCP local (incluido `.mcpb`) ignorado** en chat (sí en
  Cowork en tu PC); `bin/` hace que **no se instale**. **[DOC]**
  [plugins/platform-support](https://claude.com/docs/plugins/platform-support).
- Los plugins de chat/Cowork vienen de la **cuenta** (Customize > Plugins, o subir un zip), no de la
  máquina; los instalados con `claude plugin install` no suben a la cuenta. **[DOC]** (misma página).
- Mods: no aparecen en la lista de superficies del chat; la doc los define como de Claude Code. **[DOC]**
  ([mods](https://code.claude.com/docs/en/plugins/mods), [platform-support](https://claude.com/docs/plugins/platform-support)).
- Un conector remoto del chat se llama «through Anthropic's infrastructure» (desde la nube), así que
  **no alcanza `127.0.0.1:9393`**. **[DOC]** [connectors/building/mcpb](https://claude.com/docs/connectors/building/mcpb.md) («Remote connectors run on your servers via HTTPS and are accessed through Anthropic's infrastructure») + **[INF]**.
- Cowork «sources its skills, plugins, and connectors from this Customize configuration, which syncs
  through your claude.ai account, not from the CLI's `~/.claude` directory». **[DOC]** (desktop).

**Conclusión 1:** para local-delegate, la pestaña Code se cubre con el plugin de Claude Code tal cual;
el chat solo admite un MCP local stdio (config o `.mcpb`) y, de lo demás, solo skills de la cuenta.

## 2. Chat de Desktop: cómo distribuir el MCP

### 2.1 Estado real de esta PC

- Desktop es paquete MSIX `Claude 3.1623.0.0` (`C:\Program Files\WindowsApps\Claude_3.1623.0.0_x64__pzs8sxrjxfjjc`). **[PRUEBA]**
- Config vigente: `%APPDATA%\Claude\claude_desktop_config.json` (modificada 2026-10-20), claves de
  primer nivel `globalShortcut, mcpServers, coworkUserFilesPath, preferences`; 23 servidores. Hay otra
  copia vieja en `…\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude-3p\` (2026-04-16), ajena. **[PRUEBA]**
- Entrada `local-delegate`: `command: npx`, `args: -y | mcp-remote@latest | http://127.0.0.1:9393/mcp |
  --header | Authorization: Bearer <literal>`, sin `env`; ningún `${` en todo el fichero. **[PRUEBA]**
  (token no impreso).
- **Los logs se mudaron**: los de `%APPDATA%\Claude\logs\` se pararon el 2026-08-31; los vivos están en
  `%LOCALAPPDATA%\Claude\Logs\` (`mcp.log`, `mcp-server-local-delegate.log`, 2026-10-21). **[PRUEBA]**
  → Cualquier check/documento que mire la ruta vieja está mirando un log muerto.
- El log de hoy muestra `Using custom headers: Authorization` y `Proxy established successfully`
  varias veces: la entrada con espacios en `args` **funciona** (el bug de espacios en Windows que
  avisa `mcp-remote` no muerde aquí); desde el 2026-10-20 Desktop lanza `npx.cmd` directo en vez de
  `cmd.exe`. **[PRUEBA]** + **[3º]** [mcp-remote README](https://github.com/geelen/mcp-remote).
- `mcp.log` solo vuelca `paths` (el PATH, 31 entradas, con las de usuario como `C:\Users\Yohan\.local\bin`),
  ningún otro nombre de variable. **[PRUEBA]**

### 2.2 `.mcpb` (antes `.dxt`)

- Es la vía oficial para empaquetar un **MCP local** para Desktop: zip con `manifest.json`, «The
  server runs on the user's machine over stdio». Desktop trae Node propio. **[DOC]**
  [connectors/building/mcpb](https://claude.com/docs/connectors/building/mcpb.md).
- Formato: `manifest_version` 0.3 (la spec cita 0.4 para `uv`); `server.type` ∈ `node | python |
  binary | uv`; `mcp_config {command,args,env}` con `${__dirname}`, `${HOME}`, `${user_config.KEY}`…;
  `platform_overrides` por `win32/darwin`; `user_config` tipos `string|number|boolean|directory|file`,
  `sensitive: true` = enmascarado y guardado seguro. **[DOC]**
  [MANIFEST.md](https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md).
- Dónde va lo sensible: «Credential Manager on Windows», Keychain en macOS. **[DOC]**
  [support 10949351](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).
- **Servidor HTTP remoto**: la spec no tiene tipo HTTP; solo stdio. **[DOC]** (MANIFEST.md). Pero la
  propia doc dice que «Organizations commonly build MCPBs as secure proxies to internal MCP servers».
  → Una `.mcpb` tipo `node` que **empaquete `mcp-remote` fijado** y le pase
  `--header Authorization:Bearer ${user_config.token}` (token en Credential Manager) alcanza el daemon
  local con cabecera. **[INF]**, no probado. Variante: tipo `uv`/`binary` que arranque local-delegate en
  modo stdio, descartada porque saltaría el daemon único **[INF]**.
- Ventaja colateral: hoy la entrada corre `npx -y mcp-remote@latest` en cada arranque (versión sin
  fijar, contra la regla de cadena de suministro del usuario); la `.mcpb` lo dejaría fijado y auditado
  con Socket. **[PRUEBA]** (entrada leída) + **[INF]**.
- **Instalación sin interacción: no hay vía documentada.** Doble clic, arrastrar o Settings >
  Extensions > Advanced > Install Extension…; «Each of these install methods opens an installation UI
  where the user reviews … and completes installation». Despliegue masivo solo para Team/Enterprise
  (subida del Owner, allowlist). **[DOC]** (mcpb.md, support 10949351). Lo más cerca: `install` genera
  la `.mcpb` y la abre (`start file.mcpb`) para que el usuario confirme. **[INF]**
- Lo instalado vive en `%APPDATA%\Claude\Claude Extensions\<id>\`, ajustes en
  `Claude Extensions Settings\<id>.json` (`isEnabled`, `userConfig`) y registro en
  `extensions-installations.json` (`id, version, hash, installedAt, manifest, signatureInfo, source`;
  las tres de aquí: `manifest_version 0.3`, `source=registry`, `unsigned`). **[PRUEBA]** → `doctor`
  podría leer esto para saber si la extensión está y habilitada (formato **no documentado**).
- El directorio ya no acepta `.mcpb` («Desktop extension listings in the directory are deprecated»);
  para el directorio, un servidor local va dentro de un plugin. **[DOC]** (mcpb.md).
- Un plugin de Claude Code puede llevar una `.mcpb` (`"mcpServers": "./servers/x.mcpb"`) y
  `claude plugin install --config <server>.<key>=<value>` rellena su `user_config` sin diálogo (≥ 2.1.285).
  **[DOC]** [plugins/components#include-a-packaged-mcpb-server](https://code.claude.com/docs/en/plugins/components).
  Útil para reutilizar el mismo artefacto, pero en el chat un plugin con MCP local se **ignora**.

### 2.3 `${VAR}` en `claude_desktop_config.json` (la duda del backlog §3)

- La doc oficial de Desktop no dice que expanda `${VAR}`. Solo un tercero (IBM i) lo afirma. **[3º]**
  [glama/IBM ibmi-mcp](https://glama.ai/mcp/servers/@IBM/ibmi-mcp/blob/bdd94b498101779611bdbd43d33d837897cfed11/docs/clients/claude-desktop.mdx) — sin confirmar.
- **No hace falta que Desktop lo expanda**: `mcp-remote` lo sustituye en `--header` desde su propio
  `process.env` (backlog §1.1, medido en su fuente; el README lo usa así). **[3º]** [mcp-remote](https://github.com/geelen/mcp-remote).
- Lo que falta es que el proceso hijo **herede** `LOCAL_DELEGATE_WEB_TOKEN` (variable de usuario, existe:
  **[PRUEBA]**). Indicios a favor: la doc dice que la app hereda las variables de usuario en Windows
  **[DOC]**, y el PATH que vuelca el log incluye entradas del PATH de usuario **[PRUEBA]**; no es
  concluyente (Desktop podría construir el entorno del hijo). **Sigue sin medir.**
- Para medirlo **sin reiniciar Desktop ni tocar su config**: script de solo lectura
  `C:/Users/Yohan/AppData/Local/Temp/claude/D--Projects-local-delegate/ed2ae533-e76e-4dce-ae5d-1dd44f83b27e/scratchpad/r2/env-name-probe.ps1`.
  Lee el bloque de entorno del proceso `node … mcp-remote … 9393` que Desktop ya lanzó y dice solo
  `present = True/False` para un nombre (nunca el valor). Validado hoy contra el `claude.exe` de la
  CLI: control positivo `LOCAL_DELEGATE_WEB_TOKEN = True`, negativo `NO_SUCH_VAR_R2_XYZ = False`
  **[PRUEBA]**. Desktop no estaba abierto, así que contra él da `no matching process`. Uso:
  `pwsh -File …\env-name-probe.ps1 -Name LOCAL_DELEGATE_WEB_TOKEN` con Desktop abierto.
  Si da `True`, la fase B puede escribir `--header` `Authorization:Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`
  (sin espacios tras los dos puntos, como recomienda `mcp-remote`) y quitar el token literal.

## 3. Skills en Desktop

- El «registro aparte» (`%APPDATA%\Claude\local-agent-mode-sessions\skills-plugin\<sesión>\<cuenta>\manifest.json`,
  plugin sintético `anthropic-skills`) sigue ahí, **regenerado por la app el 2026-10-20**. Las cinco
  skills de usuario (`delegacion-local`, `session-memory`, `archify`, `ui-ux-pro-max`,
  `analizar-multimedia`) llevan ahora `skillId` y `backingPluginId` de servidor (`skill_01…`,
  `plugin_01…`): ya **vienen de la cuenta de claude.ai**, no de la edición a mano de julio. **[PRUEBA]**
  → La memoria `claude-desktop-skills-registry` está desfasada: editar ese manifest es inútil, la app
  lo pisa con lo de la cuenta.
- Doc: las skills de la cuenta llegan a chat, Cowork y sesiones cloud; las de `~/.claude/skills/` **no**
  salvo que se habiliten en claude.ai; las sincronizadas son de solo descarga (en la CLI caen en
  `~/.claude/skills/synced/`). **[DOC]** [skills](https://code.claude.com/docs/en/skills) (sección de sincronización).
- **Instalación programática: no hay vía documentada** para la cuenta de un usuario Pro/Max. Se sube
  a mano: skill (Customize > Skills) o plugin en zip (Customize > Plugins > Add > Upload plugin; ≤ 200 MB,
  ≤ 5 000 ficheros, sin `bin/` de primer nivel). **[DOC]** [platform-support](https://claude.com/docs/plugins/platform-support).
  La API `/v1/skills` es del espacio de trabajo de la API, no de la cuenta de claude.ai **[INF]**, no verificado.
- Consecuencia: la skill de local-delegate llega a la pestaña Code dentro del plugin; al chat, solo si
  el usuario sube el zip una vez. `install` puede **generar** ese zip (sin `bin/`, con la skill y, si
  se quiere, sin MCP local porque el chat lo ignora) y decir dónde subirlo. **[INF]**

## 4. Recomendación

### 4.1 Qué pieza llega a qué cara y por qué vía

| Pieza | Pestaña Code (Windows/macOS) | Pestaña Code en WSL | Chat de Desktop |
| :- | :- | :- | :- |
| MCP `local_*` | Plugin (`.mcp.json` http + `${LOCAL_DELEGATE_WEB_TOKEN}`) | Lo de hoy dentro de la distro | Entrada en `claude_desktop_config.json` (fase B) o `.mcpb` |
| Hooks (lectura, telemetría) | Plugin | No (sin plugins) | No existe |
| Mod (tools fijas, comandos, barra) | Plugin | No | No existe |
| Skill `local-delegation` | Plugin | `~/.claude/skills` de la distro | Subida manual a claude.ai (zip generado) |
| Agentes | Plugin | No | Ignorados |

### 4.2 Decisión previa que este informe obliga a tomar

- Con el plugin, el MCP se llama `plugin:<plugin>:<server>` y sus tools
  `mcp__plugin_<plugin>_<server>__local_summarize`, **no** `mcp__local-delegate__local_summarize`. **[DOC]**
  ([components#mcp-servers](https://code.claude.com/docs/en/plugins/components), [mcp](https://code.claude.com/docs/en/mcp)).
  Eso toca matchers de hooks, listas `tools:` de los agentes, `CLAUDE.md` gestionado, el hook de
  lectura y la telemetría. Afecta a todo el SDD, no solo a Desktop.
- En la pestaña Code, la entrada `local-delegate` de `claude_desktop_config.json` **se sigue cargando**
  junto al plugin: con nombres distintos no se deduplica, y habría dos juegos de tools. **[DOC]** + **[INF]**.
  Opciones: (a) el MCP del plugin conserva el nombre de servidor y se acepta el duplicado solo en
  Desktop (mala: se duplica el catálogo); (b) **el MCP sigue fuera del plugin** (como hoy en
  `~/.claude.json`) y el plugin trae hooks, mod, skill y agentes; así los nombres no cambian y la
  entrada de Desktop sigue ganando a igual nombre; (c) tools fijas por el mod y MCP del plugin, y la
  entrada de Desktop se renombra. Mi recomendación: **(b)** para la primera versión **[INF]**: no rompe
  nombres, no duplica en Desktop, y el plugin aporta lo nuevo.

### 4.3 Los tres verbos

**`install`**
- Pestaña Code: nada específico; la instalación del plugin a nivel usuario (`claude plugin marketplace
  add <ruta local>` + `claude plugin install … --scope user`) ya la cubre. **[DOC]**
- Chat (fase B, ya no bloqueada por el plugin): escribir **solo** `mcpServers.local-delegate` en
  `%APPDATA%\Claude\claude_desktop_config.json` con mezcla de clave (el fichero lleva 23 servidores y
  todas las preferencias), copia previa, y aviso de «reinicia Desktop». Forma: `npx` → mejor el
  `mcp-remote` **fijado** (versión exacta, auditada con Socket) en vez de `@latest`. Cabecera por
  variable **solo si** el sondeo de §2.3 da `True`; si no, literal como hoy (elección del usuario,
  backlog §1.1).
- Alternativa `.mcpb`: generar el paquete y abrirlo; requiere clic del usuario. Útil para quien no
  quiere tocar el JSON; no sustituye la escritura silenciosa.
- Skill para el chat: generar el zip y decir «súbelo en Customize > Skills/Plugins»; no hay API.
- WSL: no hacer nada con plugins; documentar el límite.

**`doctor`**
- Mantener `service.desktop_auth` y ampliarlo: (1) ruta de logs nueva `%LOCALAPPDATA%\Claude\Logs\`;
  (2) avisar si `mcp-remote@latest` (sin fijar); (3) avisar de **duplicado** si el plugin trae MCP y
  Desktop tiene la entrada; (4) si se opta por `.mcpb`, leer `extensions-installations.json` y
  `Claude Extensions Settings\<id>.json` (`isEnabled`) — formato no documentado, check en `UNKNOWN`
  si cambia; (5) versión de la pestaña Code ≥ 2.1.286 para mods (carpetas de
  `%APPDATA%\Claude\claude-code\`, no documentado; o pedir `/status`).
- Skills del chat: solo informativo (no se puede comprobar la cuenta desde local con garantías; la
  caché `skills-plugin\…\manifest.json` sirve de pista, no de verdad).

**`update`**
- Plugin: `claude plugin update <plugin>@<marketplace>`; el marketplace local trae auto-update apagado
  por defecto. **[DOC]** (plugins/install).
- Entrada de Desktop: reponer cabecera/URL si cambia la auth del daemon (el riesgo de §1.1) y fijar la
  versión de `mcp-remote` cuando suba.
- `.mcpb`: no hay actualización silenciosa documentada; habría que regenerar y reabrir. **[DOC]** + **[INF]**.

## 5. Pendientes que salen de aquí

- Medir la herencia de `LOCAL_DELEGATE_WEB_TOKEN` con el sondeo, con Desktop abierto (sin reiniciar).
- Probar en vivo que un plugin con `.mcp.json` http + `${VAR}` en `headers` expande (la doc lo dice
  para `.mcp.json` de proyecto; para plugin solo nombra los marcadores de ruta). **[DOC]** parcial.
- Actualizar la memoria `claude-desktop-skills-registry` (desfasada: ahora es caché de la cuenta) y la
  ruta de logs en el backlog §3.
- Decidir 4.2 (nombre del MCP / MCP dentro o fuera del plugin) antes de la spec.

## Fuentes

- https://code.claude.com/docs/en/desktop
- https://code.claude.com/docs/en/desktop-wsl
- https://code.claude.com/docs/en/plugins/mods
- https://code.claude.com/docs/en/plugins/install
- https://code.claude.com/docs/en/plugins/components
- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/skills
- https://claude.com/docs/plugins/platform-support
- https://claude.com/docs/connectors/building/what-to-build
- https://claude.com/docs/connectors/building/mcpb.md
- https://github.com/modelcontextprotocol/mcpb/blob/main/MANIFEST.md
- https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop
- https://www.anthropic.com/engineering/desktop-extensions
- https://github.com/geelen/mcp-remote (3º)
- https://glama.ai/mcp/servers/@IBM/ibmi-mcp/blob/bdd94b498101779611bdbd43d33d837897cfed11/docs/clients/claude-desktop.mdx (3º, sin confirmar)
