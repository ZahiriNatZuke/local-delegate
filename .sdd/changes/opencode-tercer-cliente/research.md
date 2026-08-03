# Research: opencode como tercer cliente de `install`

Todo lo de aquí está **medido por ejecución** el 2026-08-02 contra **opencode 1.18.11**
(`opencode-ai@1.18.11` de npm, binario `opencode-linux-x64/bin/opencode`), en HOMEs simulados
bajo un directorio de trabajo. **No** está leído de la documentación: `opencode.ai` está bloqueado
por la política de red de este entorno, así que la fuente fue el binario y su propia salida.

Reproducir: `npm install opencode-ai@1.18.11` y ejecutar el binario con `HOME=<árbol simulado>`.

## Current behavior

`install` conoce **dos** clientes y la lista está repartida en cinco sitios:

| Sitio | Qué dice |
|---|---|
| `cli.py:33` | `_ALL_TARGETS = ("claude", "codex")` |
| `cli.py:34` | `_CLIENT_DIR = {"claude": "~/.claude", "codex": "~/.codex"}` |
| `cli.py:753,760` | `choices` de `--target` y `--clients` |
| `install.py:99` | `present_targets`: `(("claude", ".claude"), ("codex", ".codex"))` |
| `checks.py:361` | `_probe_clients`: `("Claude Code", claude_dir), ("Codex", codex_dir)` |

Y cada componente de `plan_install` se ramifica por `"claude" in opts.targets` /
`"codex" in opts.targets` (`install.py:533-640`).

## R1 — opencode NO hereda la configuración MCP de Claude Code ni de Codex

Medido con un HOME que tenía `~/.claude.json` con `mcpServers.local-delegate` y
`~/.codex/config.toml` con `[mcp_servers.local-delegate]`, y **nada** en `~/.config/opencode`:

```
$ HOME=<h8> opencode mcp list
!  No MCP servers configured
$ HOME=<h8> opencode debug config
{ "$schema": "...", "agent": {}, "mode": {}, "plugin": [], "command": {}, "username": "unknown" }
```

Es el hallazgo que justifica el change entero: **sin escribir la entrada, no hay integración**.
Ojo con la confusión fácil — opencode sí tiene compatibilidad con Claude Code, pero para
*prompts* y *skills* (R9, R10), **no** para MCP.

## R2 — Dónde vive la configuración global, y que respeta `HOME`

```
$ HOME=<h1> opencode debug paths
home       <h1>
config     <h1>/.config/opencode
data       <h1>/.local/share/opencode
cache      <h1>/.cache/opencode
state      <h1>/.local/state/opencode
```

`~/.config/opencode` sale de `HOME` (respeta también `XDG_CONFIG_HOME`). Consecuencia práctica que
lo diferencia de Claude Code: **`--home` sigue siendo un sandbox de verdad** aunque se invoque el
binario del cliente, porque no hay ningún equivalente al `--scope user` de `claude mcp add-json`
que escriba siempre en el HOME real. La regla `is_simulated_home` **no** tiene que apagar el
camino por CLI para opencode.

El propio opencode lo dice en su skill interna (`opencode debug skill`, entrada
`customize-opencode`): *«Global config: `~/.config/opencode/opencode.json` (NOT `~/.opencode/`)»*.

**R2-A — `XDG_CONFIG_HOME` gana sobre `HOME`.** Medido:

```
$ HOME=<h9> XDG_CONFIG_HOME=<h9>/xdg opencode debug paths
home       <h9>
config     <h9>/xdg/opencode        # NO <h9>/.config/opencode
```

Es el motivo de que «dónde está el config de opencode» tenga que ser **una función**, no una
propiedad `home / ".config" / "opencode"` escrita en dos sitios: con la variable puesta —y hay
distribuciones y dotfiles que la ponen— esa ruta sería mentira, y `install` escribiría un fichero
que opencode nunca lee. Con la deducción correcta, en cambio, `doctor` y `install` coinciden.

## R3 — `opencode.json` y `opencode.jsonc` se leen **los dos**, y se fusionan

Con los dos ficheros presentes, cada uno con una entrada MCP distinta:

```
$ HOME=<h4> opencode debug config
{ "mcp": { "de-json": {...}, "de-jsonc": {...} }, ... }
```

No es «gana uno»: es deep-merge. Para el `probe` significa que hay que **mirar los dos ficheros**,
o se dará por ausente una entrada que está.

## R4 — La CLI: `opencode mcp add` sirve, `opencode mcp remove` **no existe**

`opencode mcp --help` lista exactamente: `add`, `list`, `auth`, `logout`, `debug`. No hay `remove`.

`add` es utilizable de forma no interactiva y es el análogo del `claude mcp add-json`:

```
# remoto
$ HOME=<h> opencode mcp add local-delegate --url http://127.0.0.1:9393/mcp \
      --header "Authorization=Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}"
# local (stdio): el comando va tras `--`
$ HOME=<h> opencode mcp add local-delegate \
      --env "LOCAL_DELEGATE_API_KEY={env:LOCAL_DELEGATE_API_KEY}" \
      -- uvx --from local-delegate-mcp==0.21.0 local-delegate-mcp
*  MCP server "local-delegate" added to <h>/.config/opencode/opencode.jsonc
```

Cuatro propiedades medidas, todas las que hacen falta:

1. **Escribe en el config global** y respeta `HOME`.
2. **Conserva lo ajeno**: un `// comentario del usuario` y una clave `"theme"` seguían ahí después.
3. **Es idempotente**: repetir el `add` con el mismo nombre **reemplaza** la entrada entera (se vio
   desaparecer el `headers` de la vuelta anterior), no duplica ni falla.
4. **Elige fichero como nosotros necesitaremos elegirlo**: escribe en `opencode.json` si existe;
   si no, en `opencode.jsonc`; si no hay ninguno, **crea `opencode.jsonc`** (y un `.gitignore` al
   lado) con `{"$schema": "https://opencode.ai/config.json"}`.

La ausencia de `remove` es la asimetría que condiciona el diseño: **el `uninstall` no puede
delegar en el cliente**.

## R5 — La forma de la entrada, y que `{env:VAR}` se sustituye

Escrito a mano y comprobado con `debug config`, que imprime la configuración **ya resuelta**:

```jsonc
// local (stdio)
"local-delegate": {
  "type": "local",
  "command": ["uvx", "--from", "local-delegate-mcp==0.21.0", "local-delegate-mcp"],
  "enabled": true,
  "environment": { "LOCAL_DELEGATE_API_KEY": "{env:LOCAL_DELEGATE_API_KEY}" }
}
// remoto (HTTP contra el daemon)
"local-delegate": {
  "type": "remote",
  "url": "http://127.0.0.1:9393/mcp",
  "enabled": true,
  "headers": { "Authorization": "Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}" }
}
```

Con `LOCAL_DELEGATE_API_KEY=secreto-medido` en el entorno, `debug config` devolvió
`"LOCAL_DELEGATE_API_KEY": "secreto-medido"`; con `LOCAL_DELEGATE_WEB_TOKEN=tok-medido`,
`"Authorization": "Bearer tok-medido"`. O sea: **la sustitución funciona en los dos sitios que nos
importan**, y por tanto el secreto **nunca hay que escribirlo** — igual que hoy con
`${LOCAL_DELEGATE_API_KEY}` en Claude Code y `env_vars` en Codex, pero con otra sintaxis.

`${VAR}` **no** se sustituye (lo dice la skill interna y es coherente con lo medido). Escribir la
forma de Claude Code aquí dejaría la variable literal en el entorno del proceso hijo.

Notas de forma, de la skill interna: `type` es **obligatorio**; `command` es **siempre un array**;
`environment` (no `env`) es la clave de variables; `enabled: false` sirve para desactivar sin
borrar.

## R6 — Modo de fallo: una clave desconocida deja el cliente sin arrancar

```
$ cat opencode.json → { "local_delegate_marker": "nuestro", "mcp": {} }
$ HOME=<h7> opencode debug config
Error: Configuration is invalid at <h7>/.config/opencode/opencode.json
↳ Unrecognized key: local_delegate_marker
```

Dos consecuencias directas:

- **No hay marcadores propios posibles** al estilo de `local-delegate:begin/end`. La identidad de
  «lo nuestro» tiene que ser **la clave `local-delegate` dentro de `mcp`**, exactamente como en
  Claude Code (`mcpServers.local-delegate`), y no como en Codex.
- El coste de una escritura mal formada es **más alto** que en los otros dos clientes: no deja una
  entrada rota, deja al usuario sin poder abrir opencode. De ahí que el camino por defecto sea la
  CLI del propio cliente y que el `.bak` no sea opcional.

**R6-A — Los comentarios se aceptan aunque el fichero se llame `.json`.** Un
`{ // comentario \n "mcp": {...} }` en `opencode.json` se leyó sin queja. Es decir: un
`json.loads` + `json.dumps` de ida y vuelta **borraría comentarios legítimos del usuario** sin
que el fichero pareciera inválido. Este es el riesgo real del camino sin CLI.

**R6-B — Un config roto no se empeora.** Con `{ "mcp": { roto`, `opencode mcp add` falla con un
error que señala línea y columna y **no toca el fichero**.

## R7 — Qué dice opencode de sí mismo por MCP

Se levantó un servidor MCP stdio de pega que anota el `initialize` y se listó con
`opencode mcp list` (que **sí conecta**: mostró `✓ spy connected`):

```json
{"method":"initialize","params":{
  "protocolVersion":"2025-11-25",
  "capabilities":{"roots":{}},
  "clientInfo":{"name":"opencode","version":"1.18.11"}},"jsonrpc":"2.0","id":0}
```

Tres datos que se usan tal cual:

- El nombre con el que aparecerá en `clients.jsonl` y en el check `client.observed` es
  **`opencode`** (Claude Code dice `claude-code`).
- Negocia **`2025-11-25`**, la misma revisión que Claude Code (Codex negocia `2025-06-18`).
- **No declara `elicitation`**: solo `roots`. `preguntas.puede_preguntar()` devuelve `False` en ese
  caso y quien llama sigue haciendo lo de antes, así que **no hay nada que cambiar** en el
  servidor — pero tampoco hay que prometer que opencode preguntará.

Además, `opencode mcp list` conecta de verdad contra el servidor: es el comando de verificación
que la documentación debe ofrecer, el equivalente de `claude mcp list` / `codex mcp list`.

## R8 — La skill se carga sola desde `~/.claude/skills/`… y esa es justo la trampa

Con un HOME que solo tenía `~/.claude/skills/delegacion-local/SKILL.md` (copiada del paquete):

```
$ HOME=<h5> opencode debug skill
[ { "name": "customize-opencode", ... },
  { "name": "delegacion-local", "location": "<h5>/.claude/skills/delegacion-local/SKILL.md", ... } ]
```

O sea: en una máquina que ya tiene Claude Code configurado, la skill **ya funciona en opencode sin
tocar nada**. Pero eso no vale como diseño, por dos motivos independientes:

1. En una máquina **solo con opencode** no existe `~/.claude/skills`, y `plan_install` solo escribe
   la skill si `"claude" in opts.targets`. Crearle un `~/.claude/` a quien no tiene Claude Code es
   exactamente lo que se corrigió al retirar el default `--target all`.
2. Es una compatibilidad **apagable**: `OPENCODE_DISABLE_EXTERNAL_SKILLS=1` y
   `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` existen en el binario y la desactivan.

La ubicación propia, según la skill interna del cliente, es
`~/.config/opencode/skill(s)/<nombre>/SKILL.md`.

## R9 — La memoria: opencode lee **los dos** ficheros, no «el primero que encuentre»

Extraído del propio binario (la lista de ficheros de instrucciones globales):

```js
n = [ join(config, "AGENTS.md"),
      ...(!t.disableClaudeCodePrompt ? [ join(home, ".claude", "CLAUDE.md") ] : []) ]
```

Es una **lista**, no un `??`: `~/.config/opencode/AGENTS.md` **y** `~/.claude/CLAUDE.md`, salvo que
`OPENCODE_DISABLE_CLAUDE_CODE_PROMPT` esté puesta (la cadena está en el binario). El mismo
razonamiento de R8 aplica: útil de regalo en una máquina mixta, insuficiente como diseño en una
máquina solo con opencode, y apagable.

## R10 — Los hooks no portan

opencode no tiene el mecanismo de hooks de Claude Code. Su punto de extensión son **plugins** en
TypeScript/JavaScript (`~/.config/opencode/plugin/*.ts`, o la clave `plugin` del config), que
exportan una función y devuelven un objeto de hooks con otra superficie:
`tool.execute.before`, `tool.execute.after`, `chat.message`, `chat.params`, `permission.ask`,
`command.execute.before`, `shell.env`, …

Nuestros tres hooks (`suggest_delegate_prompt.py`, `suggest_lint_summary.py`,
`suggest_delegate_read.py`) son scripts de **Python** que leen por stdin el JSON de Claude Code y
responden en su formato. No hay traducción mecánica: habría que reescribirlos en TS y volver a
medir si sugieren cuando toca (el piloto A/B de `docs/recipes/claude-code-hooks.md`). **Fuera de
alcance**, y dicho en el brief para que no parezca un olvido.

## R11 — Lo que cuesta, en ficheros

| Fichero | Qué cambia |
|---|---|
| `install.py` | `present_targets`, `mcp_entry` → forma de opencode, escritor/borrador del config, ramas de `plan_install`/`plan_uninstall` para mcp+memory+skill |
| `cli.py` | `_ALL_TARGETS`, `_CLIENT_DIR`, `choices` de `--clients`/`--target`, texto de ayuda |
| `checks.py` | `_probe_clients`, `_probe_memory`, `_probe_mcp_credential`, nuevo `_probe_mcp_opencode`, `CHECKS` (16 → 17) y las **cinco** frases de tamaño |
| `update.py` | dos `Repair` nuevos y el comentario de no reparables |
| `tests/` | `test_install.py`, `test_install_clients.py`, `test_checks.py`, `test_update.py`, `conftest.py` |
| `docs/` | `wiki/Integration-install.md`, `wiki/Daemon.md`, `README.md`, `CHANGELOG.md` |

Nada de esto pide arquitectura nueva: el `Options.targets` ya es un `set[str]` y `apply()` ya es
agnóstico. El trabajo es **ensanchar un eje que ya existe**, no abrir uno.

## Veredicto de viabilidad

**Viable, y de dificultad media-baja.** Las tres cosas que podían haberlo hundido —que no hubiera
forma de referenciar un secreto sin escribirlo, que no hubiera CLI y hubiera que reescribir JSONC
a mano, que opencode heredara la config de otro cliente y el change sobrara— están las tres
medidas y ninguna se cumple. Lo que queda es trabajo conocido, del mismo tamaño que
`install-checks-clients`.

Los dos riesgos que sí quedan son de **cuidado en la escritura**, no de viabilidad: el hard-fail
por clave desconocida (R6) y la pérdida de comentarios en el camino sin CLI (R6-A). Los dos se
atacan en el plan con la misma regla que ya gobierna el Codex ajeno: *no se pisa configuración
escrita por una persona*.
