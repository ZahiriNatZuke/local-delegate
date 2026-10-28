# Instalación de la integración (`install` / `uninstall`)

Instalar el MCP nunca fue solo registrar el servidor: las tools se usan de verdad cuando el
cliente además tiene los **hooks**, la **skill** y la **regla en memoria**. `local-delegate
install` deja las cuatro piezas puestas de una vez, de forma idempotente y reversible.

```bash
uv tool install local-delegate-mcp   # deja `local-delegate` en el PATH (recomendado)
local-delegate install --dry-run     # muestra cada cambio, sin escribir
local-delegate install               # aplica
local-delegate uninstall             # revierte solo lo que instaló
```

> **Sobre `uvx`.** `uvx local-delegate-mcp install` funciona y deja el andamiaje idéntico, pero
> **no instala el comando**: `uvx` monta un entorno efímero para esa ejecución y lo borra al
> terminar. El resultado desconcierta —todo queda configurado y `local-delegate doctor` responde
> «command not found»—, así que desde la 0.15.0 el `install` lo avisa al terminar y el `doctor` lo
> reporta como `[FALT]` con el comando que lo arregla.

## Qué instala

| Componente | Destino | Notas |
|---|---|---|
| Entrada MCP | Claude Code (`claude mcp add-json --scope user`, o `~/.claude.json` si no está la CLI), `~/.codex/config.toml` y opencode (`opencode mcp add`, o `~/.config/opencode/opencode.json[c]` si no está la CLI) | `stdio` con `uvx` por defecto; `--mcp-mode http` apunta al daemon compartido |
| Hooks | `~/.claude/hooks/local-delegate/` + registro en `~/.claude/settings.json` | `UserPromptSubmit`, `SubagentStart` (recordatorio de cargar las tools `local_*` en cada subagente) y `record_call.py` (`PreToolUse` sobre `mcp__local-delegate__.*`) siempre; los de lectura (`PreToolUse`/`Read` y `PreToolUse`/`Bash\|PowerShell`) solo con `--enable-read-hook`, que los deja activos. `record_call.py` (antes `anotar_llamada.py`) no avisa ni bloquea: anota qué agente pidió cada delegación, con qué esfuerzo y en qué transcript, para que el log de uso guarde su modelo (ver [Savings & metrics](Savings-and-metrics.md#coste-equivalente-a-precio-de-api)) |
| Skill | `~/.claude/skills/local-delegation/SKILL.md` y `~/.config/opencode/skill/local-delegation/SKILL.md` | regla de oro + catálogo de tools |
| Memoria | bloque entre marcadores en `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` y `~/.config/opencode/AGENTS.md` | resumen corto de la regla, siempre cargado |
| Idioma | `language.json` en el directorio de datos | el idioma de la sesión en que corre `install` (o `update`), para el daemon y los hooks, que no ven tu shell. La skill, el bloque y el catálogo de los subagentes se escriben en ese idioma. Ver [Idioma](Language.md) |
| Autocompletado del shell (opt-in) | fichero de completado y `installed.json` en `<datos>/completion/`, más un bloque entre marcadores en el perfil de PowerShell, zsh o bash | solo con `--shell-completion`; ver [Autocompletado del shell](#autocompletado-del-shell) |

## A quién configura

Por defecto (`--clients auto`), **solo los clientes que están instalados**: se mira si existen
`~/.claude`, `~/.codex` y el directorio de configuración de opencode. En una máquina con un solo
cliente ya no se crea el directorio del otro, que era lo que pasaba con el antiguo default
`--target all`.

```bash
local-delegate install                      # los que estén instalados
local-delegate install --clients codex      # ese, exista o no (orden explícita)
local-delegate install --clients opencode   # idem
local-delegate install --target all         # los tres, como antes
```

> **Dónde está la configuración de opencode.** En `~/.config/opencode/`, **no** en `~/.opencode/`,
> y `XDG_CONFIG_HOME` gana sobre el HOME si está puesta — medido contra opencode 1.18.11 con
> `opencode debug paths`. El paquete deriva esa ruta en un solo sitio
> (`install.opencode_dir`), así que `install` y `doctor` miran siempre el mismo fichero.
> Con `--home` la variable se ignora, para que el árbol simulado siga siendo un sandbox.

Si no hay ninguno, no se escribe nada, se dice qué se buscó y el comando termina bien (exit 0).

## Garantías

- **Idempotente.** Los bloques de Markdown/TOML van entre marcadores `local-delegate:begin/end`
  y se reemplazan, nunca se duplican; los hooks se desregistran antes de volver a registrarse.
- **No pisa nada ajeno.** Los hooks de terceros, el resto de `settings.json`, el resto de tu
  `CLAUDE.md` y las otras entradas de `config.toml` se conservan intactos.
- **Pregunta antes de reemplazar tu entrada MCP de Codex.** Si en `~/.codex/config.toml` hay una
  sección `[mcp_servers.local-delegate]` que escribiste tú (sin marcadores), `install` pide
  confirmación. Sin terminal para preguntar —CI, salida redirigida— la conserva y sigue con el
  resto; `--force-mcp-codex` la reemplaza sin preguntar. Al **desinstalar** sí se quita sin
  preguntar: ahí retirarla es justo lo que pediste.
- **`--home` es de verdad un sandbox.** Con un HOME simulado no se invoca el binario `claude`,
  porque `claude mcp add-json --scope user` escribe siempre en tu `~/.claude.json` real, ignore
  lo que ignore el `--home`.
- **Backups.** Cada archivo compartido que se edita deja un `.bak` al lado, **una sola vez**: la
  primera que local-delegate lo toca. Después no se pisa (ni uno `.bak` que ya fuera tuyo), así que
  guarda el estado de antes de la integración. Si el resultado es idéntico al fichero, no se
  reescribe ni se crea `.bak`.
- **Escrituras atómicas (desde la 0.44.0).** `~/.claude.json`, `~/.claude/settings.json` y el resto
  se escriben en un temporal de la misma carpeta y se reemplazan de golpe, conservando BOM, fin de
  línea y permisos: un corte a mitad no deja el fichero truncado. Justo antes de reemplazar se relee:
  si Claude Code lo guardó entretanto, el cambio se reaplica sobre lo nuevo; si vuelve a cambiar, o
  en Windows sigue bloqueado, la acción falla con un mensaje claro sin tocarlo.
- **Solo UTF-8 (desde la 0.44.0).** Un `CLAUDE.md`, `AGENTS.md`, `config.toml` de Codex o
  `~/.claude.json` que no esté en UTF-8 (cp1252, UTF-16) o no se pueda abrir no se reescribe: la
  acción falla diciendo qué fichero es y lo deja intacto. Guárdalo en UTF-8 y repite. Un UTF-8 con
  BOM sí vale. `update` cambia el pin de versión solo en la entrada de local-delegate.
- **Sin secretos.** `--api-key-env` reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno
  (`${LOCAL_DELEGATE_API_KEY}` en Claude Code, `env_vars` en Codex, `{env:LOCAL_DELEGATE_API_KEY}`
  en opencode — cada uno tiene su sintaxis y la del otro **no** se expande): la key nunca se escribe.
- **Con opencode, no se pisa un fichero que lleve comentarios.** Su configuración es JSONC y
  admite comentarios aunque el fichero se llame `.json`; reescribirla con un serializador de JSON
  los borraría **sin que el fichero pareciera roto**. Por eso el camino normal es su propia CLI
  (`opencode mcp add`, que los conserva), y cuando esa CLI no está y el fichero tiene comentarios
  —o no se puede parsear— la entrada MCP **no se escribe**: se avisa con la ruta y se sigue con el
  resto de componentes. Instalar la CLI de opencode y repetir el `install` lo resuelve.
- **En opencode nunca se escribe una clave que no sea `mcp`.** Una clave de primer nivel ajena al
  esquema puede dejar el cliente sin arrancar, y **cuánto** depende de su versión: medido el
  2026-09-08 con los dos binarios a la vez, opencode `1.18.11` rechaza el config entero
  (`Unrecognized key`) y `1.18.29` ya tolera esa clave. Como la versión la eliges tú y no nosotros,
  la regla se mantiene en su forma estricta; lo que **no** ha cambiado en ninguna versión es que
  una entrada mal formada *dentro* de `mcp` —sin `type`, sin `command`, o con `command` que no sea
  un array— sí impide arrancar. Por eso ahí no hay marcadores `local-delegate:begin/end`: la
  entrada se identifica por su nombre, como en Claude Code. Consecuencia: en opencode no hay
  pregunta previa equivalente a `--force-mcp-codex`, porque no hay forma de distinguir una entrada
  nuestra de una que escribiste tú.
- **El perfil del shell, intacto fuera del bloque.** El autocompletado es opcional
  (`--shell-completion`) y reversible: `uninstall` deja el perfil byte a byte como estaba. Se
  respeta la codificación del perfil (UTF-8 con o sin BOM, UTF-16 con BOM o ANSI, como un perfil de
  Windows PowerShell 5.1 con tildes), su fin de línea y los enlaces simbólicos (se escribe en el
  destino). La copia va a `<perfil>.local-delegate.bak`, nunca al `.bak` que pueda ser tuyo. Un
  perfil que no se puede leer, con bytes NUL sin marca de UTF-16 o con un marcador sin pareja no se
  toca, y se avisa.
- **Reversible.** `uninstall` borra los directorios propios y quita solo sus entradas.

## Comprobarlo desde el propio cliente

Cada cliente sabe decir si ve el servidor, y eso comprueba el camino entero —no solo que el
fichero esté escrito—:

```bash
claude mcp list
codex mcp list
opencode mcp list      # debe decir: ✓ local-delegate connected
```

> **opencode no puede responder preguntas.** Declara la capability `roots` pero **no**
> `elicitation` (medido contra la 1.18.11), así que las tools que saben preguntar en vez de fallar
> —backend caído, modelo inexistente, `output_format` vacío— con opencode vuelven al mensaje de
> error de siempre. No es un fallo de la instalación y `doctor` lo enseña en la línea
> «clientes MCP observados».

## Opciones

| Flag | Efecto |
|---|---|
| `--dry-run` | describe los cambios sin escribir nada |
| `--clients auto \| claude \| codex \| opencode` | cliente(s) a configurar (repetible; default `auto`) |
| `--force-mcp-codex` | reemplaza sin preguntar una entrada de Codex escrita a mano |
| `--target claude \| codex \| opencode \| all` | histórico, equivale a `--clients`; `all` fuerza los tres aunque no estén instalados. No se combina con `--clients` |
| `--no-hooks` / `--no-skill` / `--no-memory` / `--no-mcp` | excluye ese componente |
| `--agents` | actualiza tus subagentes de `~/.claude/agents/` (opt-in, ver abajo) |
| `--enable-read-hook` | registra **y enciende** los dos hooks de lectura: `PreToolUse`/`Read` y `PreToolUse`/`Bash|PowerShell`. Van juntos porque son una regla sola sobre dos caminos —cerrar `Read` y dejar `cat informe.md` abierto solo muda la conducta de sitio—. Registra además el mismo hook para las tools de lectura de otros MCP (`mcp__*__read_*`, `mcp__*__get_file_contents`), que solo dejan el evento (`camino: mcp`) y nunca bloquean. Antes solo registraba: el script exigía además `LD_HOOK_READ_ENABLED=1` y la bandera no encendía nada. El **bloqueo** viene aparte y apagado (`LD_HOOK_READ_BLOCK`, ver Configuration) |
| `--mcp-mode stdio\|http` | proceso por sesión (`uvx`) o daemon compartido en `/mcp`. **Si tu backend exige API key, `http` suele ser la única opción que funciona**: el proceso `stdio` lo lanza el cliente y hereda *su* entorno, no el del lanzador del daemon, que es quien tiene el secreto. Lo avisa el check «credencial del backend» |
| `--base-url URL` | fija `LOCAL_DELEGATE_BASE_URL` en la entrada MCP (backend remoto) |
| `--api-key-env` | reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno |
| `--web-token-env` / `--no-web-token-env` | con `--mcp-mode http`, pone o quita la cabecera `Authorization` que referencia `LOCAL_DELEGATE_WEB_TOKEN`. **Sin ninguno de los dos, se conserva la cabecera que ya tuviera cada cliente**, así que reinstalar no deja a nadie en `401` |
| `--pin-version X.Y.Z` | fija la versión del paquete en la entrada MCP |
| `--python RUTA` | intérprete con el que corren los hooks (default `python3`, `python` en Windows) |
| `--home RUTA` | HOME alternativo (útil para probar la instalación en un sandbox) |
| `--no-client-cli` | no usar el binario `claude`; edita `~/.claude.json` directamente |
| `--shell-completion [auto \| powershell \| zsh \| bash]` | deja cargado el autocompletado de la CLI en el perfil del shell (sin valor, `auto`: los de esta máquina; repetible). En `uninstall`, quita solo el autocompletado. Ver [Autocompletado del shell](#autocompletado-del-shell) |

El intérprete por defecto **no** es el que ejecuta el instalador: bajo `uvx` ese vive en un
entorno efímero que desaparece al terminar el comando y dejaría los hooks apuntando a una ruta
inexistente.

## Mantener tus subagentes al día: `--agents`

Si tienes subagentes en `~/.claude/agents/` que delegan en local-delegate, cada tool nueva del MCP
los deja desactualizados: hay que añadirla a su `tools:` y refrescar el catálogo que traen en
prosa. `--agents` lo hace por ti.

```bash
local-delegate install --agents --dry-run   # enseña qué agentes cambiarían
local-delegate install --agents             # aplica
```

Es **opt-in a propósito**, y es el único componente que se pide en vez de excluirse: los
subagentes los escribiste tú, no son andamiaje nuestro.

Cuatro reglas gobiernan lo que toca:

1. **Solo los agentes que ya declaran nuestras tools** (los que tienen
   `mcp__local-delegate__local_delegate` en su `tools:`). Un subagente ajeno ni se abre.
2. **El catálogo se deriva de la tabla de la skill**, así que dice siempre las tools que hay de
   verdad. Un test del propio paquete falla si esa tabla y el servidor MCP se separan.
3. **Fuera de los marcadores `<!-- local-delegate:catalog:begin/end -->` no se toca nada**, y si
   no se reconoce dónde va el bloque, no se inserta: no se adivina.
4. **Cada fichero modificado deja su `.bak`** la primera vez que se toca, y no se pisa después.

`update` hace una parte de esto sin `--agents`: si un subagente **ya** trae los marcadores de
catálogo y su bloque no es el del paquete (por ejemplo, el de la 0.34.0, que nombraba la skill
`delegacion-local`), regenera lo de entre los marcadores. No toca la línea `tools:` ni los
subagentes sin marcadores.

## Autocompletado del shell

`local-delegate completion powershell|zsh|bash` imprime por la salida estándar el script de
autocompletado de ese shell. Completa los subcomandos de todos los niveles, las opciones y los
**valores fijos** (los roles, la lista cerrada de `backend-params`, `--lang es|en`…), y deja los
valores libres —rutas, URLs— al completado normal del shell. El script es **estático**: cargarlo o
pulsar Tab no arranca Python (cada Tab cuesta 1–5 ms). Registra los dos nombres del comando,
`local-delegate` y `local-delegate-mcp`.

Lo normal es que lo deje cargado `install`. Es **opt-in**: sin la opción no se toca ningún perfil.

```bash
local-delegate install --shell-completion --dry-run       # enseña fichero, bloque y manifiesto
local-delegate install --shell-completion                 # los shells de esta máquina (auto)
local-delegate install --shell-completion bash            # uno concreto (repetible)
```

`--shell-completion` sin valor es `auto`: en Windows, PowerShell (las ediciones que haya, `pwsh` 7 y
Windows PowerShell 5.1); en macOS, zsh; en Linux, bash, y también zsh si tu `$SHELL` es zsh. Para
otro shell, nómbralo: `--shell-completion powershell --shell-completion bash` (se repite, no admite
comas). Un shell pedido que no está instalado se salta con un aviso y no cambia el código de
salida. Funciona aunque no haya ningún cliente (Claude Code, Codex u opencode) y se combina con
`--no-hooks --no-skill --no-memory --no-mcp` para instalar solo esto.

### Dónde escribe

| Pieza | Ruta |
|---|---|
| Fichero de completado | `<datos>/completion/local-delegate.ps1`, `local-delegate.bash` o `_local-delegate` (zsh), con `<datos>` el directorio de datos del producto: `%LOCALAPPDATA%\local-delegate` en Windows, `~/Library/Application Support/local-delegate` en macOS, `~/.local/share/local-delegate` en Linux, o `LOCAL_DELEGATE_LOG_DIR`. Las dos ediciones de PowerShell comparten el `.ps1` |
| Manifiesto | `<datos>/completion/installed.json`: qué shells, qué ficheros, qué perfiles tocó (y si los creó), en qué idioma y con qué versión. Lo leen `doctor`, `update` y `uninstall` |
| Perfil de PowerShell | `$PROFILE.CurrentUserAllHosts` de cada edición (`Documents\PowerShell\profile.ps1` y `Documents\WindowsPowerShell\profile.ps1`, siguiendo a OneDrive si redirige *Documents*); vale para la consola, Windows Terminal y VS Code. En macOS y Linux, `~/.config/powershell/profile.ps1` |
| Perfil de zsh | `${ZDOTDIR:-$HOME}/.zshrc` |
| Perfil de bash | `~/.bashrc`; en macOS, `~/.bash_profile` (Terminal abre shells de inicio de sesión, que no leen `.bashrc`). En Windows, el de Git Bash; el `bash.exe` de WSL no cuenta |

En el perfil va un bloque entre `# >>> local-delegate completion >>>` y
`# <<< local-delegate completion <<<` que solo carga el fichero **si existe**: borrar el fichero no
deja un perfil que dé error al abrir el shell. Con `--home` (sandbox), las rutas salen del HOME
simulado y el fichero va a `<home>/.local/share/local-delegate/completion/`.

### Alternativa sin `install`: cargarlo en cada sesión

Puedes añadir tú una de estas líneas al perfil en vez de usar `install`. Funciona igual, pero
**cada shell nuevo paga el arranque de Python** para generar el script:

| Shell | Línea | Coste al abrir el shell |
|---|---|---|
| PowerShell | `local-delegate completion powershell \| Out-String \| Invoke-Expression` | 0,8–2,1 s (medido: 0,8 s en 5.1 y 2,1 s en `pwsh`) |
| zsh | `source <(local-delegate completion zsh)` o `eval "$(local-delegate completion zsh)"` | 0,3–2 s |
| bash | `eval "$(local-delegate completion bash)"` (`source <(…)` también sirve en bash 4 o posterior; en el bash 3.2 de macOS usa `eval`) | lo que tarde Python en arrancar |

Con `install` el perfil solo hace *dot-source* de un fichero ya generado: 7–19 ms en PowerShell y
unos 2 ms en zsh. Por eso es lo recomendado.

### PowerShell: política de ejecución y 5.1

- **`RemoteSigned` basta** (y `Unrestricted` o `Bypass`): el fichero se genera en tu máquina, así
  que no necesita firma. `install` pregunta a cada edición su ruta de perfil y su política efectiva,
  y enseña las dos en una línea por edición, también con `--dry-run`.
- Con **`Restricted`, `AllSigned` o `Undefined`** (que en un Windows de escritorio equivale a
  `Restricted`), esa edición **se salta con un aviso**, sin tocar su perfil: un perfil que carga un
  script no firmado daría error cada vez que abres el shell. Para activarlo, en esa edición:

  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  local-delegate install --shell-completion
  ```

- Si la política no se puede consultar, se escribe igualmente y se avisa.
- El script es **solo ASCII** (las tildes de las descripciones van escapadas), así que carga igual en
  5.1 y en 7, con BOM o sin él y con cualquier página de códigos de la consola.
- **Límite de Windows PowerShell 5.1**: el motor no llama al completador cuando la palabra es `-` o
  `--` a secas, así que Tab tras `--` no ofrece nada. Escribe al menos una letra (`--r` + Tab →
  `--role`). En `pwsh` 7 no pasa.

### zsh

- El script necesita el sistema de completado de zsh (`compinit`). Si tu `.zshrc` no lo carga (el
  zsh por defecto de macOS no siempre lo hace; Oh My Zsh sí), el propio script lo carga con
  `compinit -i` antes de registrarse.
- El fichero `_local-delegate` vale también para `fpath`, si prefieres esa forma a `source`. En ese
  caso, `compinit` cachea las funciones en `~/.zcompdump`: tras regenerar el fichero, borra
  `~/.zcompdump*` y abre un shell nuevo. Con el bloque de `install` (que hace `source`) no hace
  falta.

### bash en macOS

macOS trae bash 3.2 y el script es compatible con él (no usa arrays asociativos, `compopt` ni
`mapfile`). Como `auto` en macOS solo elige zsh, pídelo explícito:
`local-delegate install --shell-completion bash`, que escribe el bloque en `~/.bash_profile`.

### Idioma y versión: regenerar con `update`

Las descripciones que enseñan PowerShell y zsh salen en el **idioma configurado en el momento de
generar** el fichero (el de `language.json`, ver [Idioma](Language.md)); bash no muestra
descripciones. Y el fichero refleja los subcomandos y opciones de la versión que lo generó. Tras
**cambiar de idioma o de versión**, regenera:

```bash
local-delegate update
```

`update` reescribe los ficheros listados en el manifiesto que no coincidan con lo que generaría
ahora, y apunta en el manifiesto el idioma y la versión nuevos. Lo hace aunque no haya ningún
cliente instalado. No crea ficheros para shells que no instalaste, no repone uno que hayas borrado
(eso es `install --shell-completion`) ni toca perfiles. Abre un shell nuevo para que cargue el
fichero regenerado.

`local-delegate doctor` lo vigila con el check «autocompletado del shell» (ver
[la tabla de checks](#comprobar-la-instalación-local-delegate-doctor)): sin nada instalado da
`[ OK ]` «no instalado (opcional)»; un fichero de otra versión o distinto, `warn` con
`local-delegate update`; un fichero ausente, un bloque borrado del perfil o ficheros sin manifiesto,
`warn` con `local-delegate install --shell-completion`. Compara en el idioma del manifiesto, así que
su veredicto no cambia con el idioma de la sesión.

### Quitarlo

```bash
local-delegate uninstall --shell-completion            # solo el autocompletado, de todos los shells
local-delegate uninstall --shell-completion zsh        # solo el de zsh
local-delegate uninstall                               # todo, autocompletado incluido
```

- `uninstall --shell-completion` no toca clientes (hooks, skill, memoria, MCP). Con `--clients` o
  `--target` explícitos, quita el autocompletado **y** esos clientes.
- Un `uninstall` **sin restricciones** también lo quita. Uno **restringido** —`--clients codex`,
  `--no-hooks` y demás— lo deja intacto. `--no-client-cli`, `--agents`, `--dry-run`, `--python` y
  `--home` no cuentan como restricción.
- Quita el bloque de los perfiles del manifiesto y de los perfiles candidatos que existan (así
  limpia aunque falte el manifiesto), borra los ficheros, el manifiesto y el directorio
  `completion/` si queda vacío. El perfil vuelve **byte a byte** a como estaba; si `install` lo creó
  y queda vacío, se borra (y su carpeta, si también la creó).
- `--dry-run` enseña cada acción, con el texto literal del bloque, sin escribir.

### Solo con el comando instalado

El completado se engancha al comando `local-delegate` (o `local-delegate-mcp`) que está en el
PATH, es decir, al que deja `uv tool install local-delegate-mcp`. Con `uvx local-delegate-mcp …` el
comando que tecleas es `uvx`, así que no hay nada que completar.

## Caso Mac → PC (backend remoto)

En la Mac, con el MCP local y la inferencia en la PC:

```bash
uvx local-delegate-mcp install \
  --base-url "https://PC_MAGICDNS:9292/v1" \
  --api-key-env \
  --pin-version 0.14.0
```

Los `path` se siguen leyendo en la Mac (que es lo que conserva el ahorro de contexto) y el
dashboard marcará esas delegaciones como **cómputo remoto**. Ver
[Backend remoto Mac → PC](./Remote-backend.md).

## Después de instalar

`install` termina imprimiendo el estado real del andamiaje —los mismos checks que el `doctor`,
con el mismo formato—, así que ya no hace falta ejecutarlo aparte para saber cómo quedó. Ese
reporte es informativo: **no** cambia el exit code, porque tras un install correcto quedan avisos
legítimos (el CLI fuera del PATH si se instaló con `uvx`, o un cliente que no está).

Reinicia el cliente. Verifica con:

- `local-delegate doctor` → comprueba de una vez las treinta y cuatro piezas (ver abajo), incluidos el
  daemon y el backend, que el reporte de `install` no mira a propósito.
- `local_status` → backend, catálogo y si el cómputo es local o remoto.
- Un prompt tipo "resume este archivo en cinco viñetas" → debe aparecer la sugerencia del hook.
- `http://127.0.0.1:9393` → panel de ahorro.

## Plazos de los clientes MCP

Una delegación puede sumar **espera de turno** (el daemon reparte el backend entre los modelos que
chocan, ver [Tools](Tools.md#turno-dos-tools-que-no-se-quitan-el-modelo)) e inferencia, y una
operación de muchos trozos ya tarda minutos. Los clientes tienen sus propios plazos para una tool
MCP, y `install` **no** los sube (pero conserva el que pongas, ver abajo). Consultados el 2026-10-07 en la documentación oficial de cada
uno:

| Cliente | Plazo | Por defecto | Cómo se sube |
|---|---|---|---|
| Claude Code | total por llamada | 28 h si `MCP_TOOL_TIMEOUT` no está puesta | `MCP_TOOL_TIMEOUT` (ms, global) o `timeout` (ms) en la entrada del servidor, que gana a la variable |
| Claude Code | **inactividad** | **5 min** en HTTP (el daemon); 30 min en stdio | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (ms; `0` lo desactiva). Un `timeout` por servidor ≥ 1000 hace de suelo |
| Claude Code | arranque | el mayor de 60 s, el plazo de tool del servidor y `MCP_TIMEOUT` | `MCP_TIMEOUT` (ms) |
| Codex | **total por llamada** | **60 s** | `tool_timeout_sec` en `[mcp_servers.local-delegate]` de `~/.codex/config.toml` |
| Codex | arranque | 10 s | `startup_timeout_sec` (o `startup_timeout_ms`) |

Las dos esperas en negrita son menores que lo que puede durar una operación con turno: en Codex se
corta **todo lo que pase de 60 s**, y en Claude Code, contra el daemon, una llamada que pase **5 min
sin respuesta ni notificación de progreso**. Si te pasa, súbelas.

**`install` y `update` conservan el plazo que pongas en la entrada `local-delegate`** (desde la
versión siguiente a la 0.33.0; antes se lo llevaban al reescribirla). Lo leen de la entrada que ya
hay y lo vuelven a escribir tal cual, en `stdio` y en `http`, también si cambias de modo. Si no
pusiste ninguno, no añaden ninguno. Se conservan estas claves:

| Cliente | Claves que se conservan |
|---|---|
| Claude Code (`~/.claude.json`) | `timeout` |
| Codex (`~/.codex/config.toml`) | `tool_timeout_sec`, `startup_timeout_sec` y `startup_timeout_ms` |
| opencode (`opencode.json`/`.jsonc`) | `timeout` |

`local-delegate doctor` enseña el plazo puesto en la línea de cada entrada (por ejemplo
`(http, plazo tool_timeout_sec = 900)`), y el `--dry-run` de `install` avisa de que lo conserva.

- **Claude Code**: pon `"timeout"` (ms) en la entrada, o usa la variable
  `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` (ms) en el entorno del cliente, por ejemplo
  `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=900000` en el bloque `env` de `~/.claude/settings.json`.
- **Codex**: añade **esta línea** a tu bloque `[mcp_servers.local-delegate]` de
  `~/.codex/config.toml`, sin tocar el resto (en modo HTTP, el bloque que escribe `install` lleva
  también `bearer_token_env_var`, y sin él el daemon con token responde `401`):

  ```toml
  # local-delegate:begin
  [mcp_servers.local-delegate]
  url = "http://127.0.0.1:9393/mcp"
  bearer_token_env_var = "LOCAL_DELEGATE_WEB_TOKEN"
  tool_timeout_sec = 900          # ← la línea que añades
  # local-delegate:end
  ```

  El siguiente `install` la mueve al final del bloque y le quita el comentario, pero conserva el
  valor.
- **opencode**: con un `timeout` en la entrada, `install` no la registra con `opencode mcp add`
  (no tiene opción para el plazo) sino escribiendo el fichero. Si el fichero tiene comentarios no
  lo reescribe: avisa y deja la entrada como estaba, con su plazo.

El plazo total de Claude Code no se extiende con notificaciones de progreso; el de inactividad sí
las cuenta como actividad. No está documentado qué
ve el modelo en Codex cuando vence el plazo, ni si cancela la petición en el servidor.

## llama-swap: residencia y grupos (`[llamaswap]`)

Con el extra `[llamaswap]` hay tres comandos sobre el `config.yaml` de llama-swap. Ninguno corre
solo: el paquete no toca la config por su cuenta.

```bash
local-delegate llamaswap residency                     # muestra; no escribe
local-delegate llamaswap residency --none --ttl gemma3-4b=120
local-delegate llamaswap residency --pin gemma3-4b --vram-gb 16 \
  --vram-model gemma3-4b=<GiB> --vram-model gemma4-26b-a4b=<GiB>   # residencia opt-in, cifras medidas
local-delegate llamaswap residency --restore config.yaml.20261007-120000.bak
local-delegate check-llamaswap --config config.yaml --vram-gb 16
local-delegate init-llamaswap --config config.yaml --swap gemma3-4b,gemma4-26b-a4b --vram-gb 16
```

- **`llamaswap residency`** sin opciones dice, por modelo, su grupo, `swap`/`exclusive`/`persistent`,
  el **TTL efectivo** (un `ttl` ausente o `-1` vale `globalTTL`, que por defecto es 0) y si está en
  `hooks.on_startup.preload`, y el veredicto: «sin residente (recomendado)» o «residente: X» por cada
  modelo con TTL efectivo 0. La config sale de `--config`, si no de `LLAMASWAP_CONFIG`, si no de la
  que usa el daemon. `--none` deja la config sin residente (mueve los miembros de los grupos
  `persistent` al grupo `swap` y pide `--ttl` para los de TTL 0); `--pin MODEL` es la **residencia
  opt-in** (grupo `persistent`, `ttl: 0`), que retiene VRAM para siempre y se niega si no cabe con
  el peor caso del resto (`--vram-gb` − `--reserve-gb`, 2 por defecto). Hoy **pide `--vram-model
  ID=GiB` para cada modelo implicado**: el estimador con `-ncmoe` no pasó su control con los modelos
  medidos (sobrestima el KV cache de los Gemma) y no se usa para decidir; `--ttl MODEL=SECONDS` cambia un TTL; `--restore BAK` vuelve a una copia.
  Escribe **solo las líneas que cambian**, deja antes una copia `<config>.<AAAAMMDD-HHMMSS>.bak`,
  reemplaza de forma atómica y no escribe con delegaciones o peticiones en curso salvo `--now`
  (`--dry-run` enseña las líneas que cambiarían). Qué dice después sobre la recarga, en
  [Troubleshooting](Troubleshooting.md#llamaswap-residency-no-escribe-o-dice-qué-hizo-llama-swap).
- **`init-llamaswap`** ya no recomienda residente: `--resident` es la residencia opt-in y
  `--ttl-resident` vale 0 por defecto (con `persistent` y TTL mayor que 0 no hay residencia de
  verdad). Con `--force`, la copia deja de ser un `.bak` fijo y lleva fecha, como la de
  `residency`.
- **El estimador de VRAM** que comparten `check-llamaswap`, `init-llamaswap` y `--pin` suma el
  fichero de `--mmproj`, resta con `-ncmoe`/`--n-cpu-moe N` los tensores de expertos de las capas
  `i < N` (que van a RAM) y trata un `--mmproj` que no existe como **error de estimación** (código 2)
  en vez de ignorarlo.

## El mod del plugin

Desde la 0.40, el plugin de Claude Code trae, además de los hooks, un **mod**: código que corre
dentro de Claude Code (`register.js`, declarado en `hooks/hooks.json` bajo `modules`). Está hecho
de **piezas**, cada una con su interruptor en la `userConfig` del plugin:

| Pieza | Interruptor | Qué hace |
|---|---|---|
| tools fijas | `pinned_tools` (lista) | saca de ToolSearch las tools de local-delegate de la lista, para que el modelo las vea sin buscarlas. Por defecto `local_summarize`, `local_extract`, `local_lint_summary` y `local_commit_msg` (~2 000 tokens). Lista vacía = apagado. Solo admite tools `mcp__local-delegate__*` |
| comandos | `commands_enabled` | `/local-summarize`, `/local-commit` y `/local-lint` sin turno del modelo |
| banda de estado | `status_enabled`, `status_style` (`bar` o `line`) | En la terminal, con `bar` (por defecto), una sola fila con el fondo de los mensajes del tema: una etiqueta de estado en vídeo inverso (` ● LISTO `, ` ◐ DELEGANDO `, ` ○ CAÍDO `, ` ◌ SIN DATOS `, ` ○ SIN SERVICIO `), el modelo atenuado, la tool en curso con su trozo (`7/9`) y lo que lleva (`4 s`, `3 min 16 s`; la más antigua y `+N` si hay varias), las delegaciones y los tokens ahorrados de **esa** sesión según el daemon (`/api/stats?session=`, `/api/backend`, `/api/inflight?session=`), el coste equivalente si `recompute-cost` dejó la cifra y, a la derecha, el modo de lectura (`lecturas: pregunta` con diálogo, `lecturas: resume solo` sin él) si `read_mod_enabled` está activo; con `line`, una raya `─` atenuada sobre una línea (`local-delegate · ● qwen3-8b listo · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18 · lecturas: pregunta`). Solo la sesión que lanzó la delegación la ve en curso: si el backend trabaja para otra sesión, la banda dice ` ● LISTO ` y, atenuado, «en uso por otra sesión», sin tool, tiempo ni trozos. Sin filas vacías. En Claude Desktop, una sola línea de texto en dos tonos, como las de la propia app (`local-delegate · ● Listo · qwen3-8b · 3 delegaciones · 12,3k tokens ahorrados ≈ $0,18`), con el color solo en el punto y el modo de lectura atenuado a la derecha; sin píldora ni enlace al panel. Se refresca sin esperar al turno: cada segundo mientras hay una delegación en curso o un modelo cargando, cada 30 s si no (solo HTTP al daemon), y al acabar una llamada a una tool de local-delegate. Sin token no dibuja nada. Se aparta ante una encuesta y quita primero lo menos importante si no cabe. No repite la cuota de Claude (la da la status line) ni usa `$.ui.status`, que Claude Code pinta con ⚠ amarillo |
| lectura | `read_mod_enabled` (encendido desde la 0.41) | resume la prosa grande (`.md`, `.txt`, `.markdown`, `.rst` por encima de `LD_HOOK_READ_SUGGEST_KB`) con `local_summarize` cuando la capa que bloquea está encendida; el código, la config y los datos pasan literales. Con diálogo pregunta, sin diálogo resume solo. Mientras actúa en una sesión, los hooks de lectura de esa sesión se apartan (ver abajo) |

Una pieza se apaga desde el menú de configuración de Claude Code (cada opción del plugin es una
fila), **no** con `claude plugin disable`, que apaga también los hooks.

Lo que el mod promete (y comprueban `tests/test_mod_static.py` y `claude plugin test`):

- Solo lee el secreto `LOCAL_DELEGATE_WEB_TOKEN`, y nunca lo escribe en un log, en la barra ni en el
  latido. Las demás variables que lee solo dicen dónde está la carpeta de datos del plugin
  (`CLAUDE_CONFIG_DIR`, `USERPROFILE`/`HOME`) y quién abrió la sesión (`CLAUDE_CODE_ENTRYPOINT`).
- Solo habla con el daemon en `http://127.0.0.1:9393`. Un daemon en otro puerto
  (`LOCAL_DELEGATE_WEB_PORT`) queda fuera del alcance del mod; los hooks y el MCP no cambian.
- Si una pieza falla, las demás siguen; si el mod entero no carga, los hooks y el MCP siguen.

`register.js` **no se versiona**: lo genera `scripts/build_mod.py` a partir de `mod/*.js` (el motor
rechaza el `import()` dinámico y solo deja pasar `$` a funciones del mismo fichero, así que pega
en él las piezas presentes y registra cada una dentro de su propio `try`). Lo corren el CI y el empaquetado antes de validar,
probar o construir la rueda. Para probar el mod en local:

```bash
uv run python scripts/build_mod.py
claude plugin validate --strict src/local_delegate/resources/claude-plugin/local-delegate
claude plugin test src/local_delegate/resources/claude-plugin/local-delegate
```

## Comprobar la instalación: `local-delegate doctor`

`install` escribe; `doctor` **solo mira**. Recorre el registro único de comprobaciones
([`checks.py`](../../src/local_delegate/checks.py)) —la misma definición de «estar a punto» que
usarán el resto de los subcomandos— y no escribe nada, ni en tu HOME ni en la configuración de
ningún cliente.

```bash
local-delegate doctor
local-delegate doctor --online       # además compara versiones del backend con GitHub
local-delegate doctor --home /tmp/x  # diagnostica contra un HOME simulado (solo lectura)
```

| Grupo | Comprobación | Qué mira |
|---|---|---|
| Entorno | CLI local-delegate | que el comando exista en el PATH — con `uvx` **no queda instalado** |
| Entorno | versión publicada | la instalada vs la última en PyPI, para que una instalación vieja no pase el diagnóstico en silencio |
| Entorno | clientes | si existen `~/.claude`, `~/.codex` y `~/.config/opencode` |
| Entorno | clientes MCP observados | con qué clientes se ha **hablado** de verdad: versión, revisión de protocolo negociada y si declaran `elicitation` (o sea, si las tools pueden preguntarles en vez de fallar). Sale de `clients.jsonl`, en `LOG_DIR`, y es **informativo**: nunca sube el exit code |
| Entorno | nombres obsoletos | nombres del registro de obsoletos que siguen puestos: variables en la shell o en el `env` de `~/.claude/settings.json`, ficheros interruptor viejos en `~/.claude` y lo que la telemetría de los hooks dice que leyeron. El aviso dice el nombre por el que cambiarlo: sin él, quien lo tuviera puesto seguiría creyendo que configura algo. Es un aviso, no un fallo. Lo que solo ve el daemon lo dice `local_status`. Desde la 0.41.0 el registro está vacío: los siete nombres retirados en la 0.38.0 dejaron de avisarse (ver [Configuración](Configuration.md#nombres-retirados-en-la-0380)), así que hoy da siempre `OK` |
| Entorno | settings.json de Claude Code | dos avisos sobre `~/.claude/settings.json`, que solo aparecen si hay algo que avisar. `warn` si el fichero **no es UTF-8 válido** aunque su contenido sea un JSON correcto, con la ruta y el byte que falla: los demás checks lo leen sustituyendo los caracteres que no entienden y no lo notarían (un UTF-8 con BOM sí es válido). Y `warn` si queda la **copia que deja la migración de nombres retirados** (`settings.json.retired-names.bak` o sus variantes con fecha, `….retired-names.<AAAAMMDDhhmmss>.bak`): da su ruta, avisa de que puede contener claves del `env` y sugiere borrarla cuando compruebes que la migración quedó bien; nunca muestra su contenido, y el aviso desaparece al borrarla. Sin `~/.claude`, `unknown` como los demás checks de Claude Code |
| Entorno | cadenas de respaldo | que cada `LOCAL_DELEGATE_FALLBACK_<ROL>` nombre solo roles (`mechanical`, `long`, `code`), el paso `loaded` o modelos del catálogo de texto —lo que no, se ignora al delegar y un rol se queda sin el respaldo que creías—; `warn` también si una variable usa `residente` o `resident`, que siguen valiendo como sinónimos obsoletos de `loaded`. Con todo bien, dice «sin residente» o «residente: X» según la config de llama-swap tenga algún modelo con TTL efectivo 0 |
| Entorno | coste y relleno | si la cifra de coste es de fiar y si se está perdiendo histórico. Lee `cost-aggregates.json` (o `coste-agregados.json` de una versión anterior, si aún no hay nuevo), el log de uso y los `attribution-AAAAMM.json` de `LOG_DIR` (o los `atribucion-AAAAMM.json` de una versión anterior, si de ese mes aún no hay nuevo), y `cleanupPeriodDays` de `~/.claude/settings.json`; **nunca** los transcripts. `warn` si hay delegaciones pendientes de relleno con más de `cleanupPeriodDays` − 10 días (30 si no está puesto: avisa a los 20), aunque `local-delegate recompute-cost` no se haya lanzado nunca, porque Claude Code borra los transcripts a ese plazo y con ellos el relleno; `warn` también si el último cotejo de la tabla de precios contra lo que cobra Claude Code falló, nombrando los modelos sin precio; `ok` si cuadró; `unknown` sin cotejo (máquina sin transcripts o comando nunca lanzado). Nunca `missing` |
| Entorno | ventanas de prueba | si `LOG_DIR/test-windows.json` (las ventanas que marca `local-delegate test-window`) se puede leer y si alguna ventana se quedó abierta. `warn` si el fichero es ilegible (con el motivo: entonces no se aparta ninguna prueba por ventana), si hay entradas ignoradas (cuántas) o si una ventana lleva abierta más de 12 h, con la orden `local-delegate test-window stop <id>` para cerrarla; `ok` sin ventanas o con todas cerradas. Nunca `missing`: una ventana mal puesta no rompe el MCP, solo aparta filas del panel |
| Andamiaje | hooks copiados | con la entrega por **plugin**, que esa carpeta esté vacía o no exista (un script ahí ya no lo ejecuta nadie: `[WARN]`, lo retira `update`). Con **settings**, los scripts en `~/.claude/hooks/local-delegate/`, y que sean **los del paquete instalado**, byte a byte. Actualizar el paquete no toca esa carpeta: con scripts de otra versión da `warn` y `update` los repone. Antes solo miraba los nombres, y unos hooks viejos pasaban por buenos |
| Andamiaje | hooks huérfanos | scripts nuestros sueltos en `~/.claude/hooks/` que dejó una instalación anterior; `install` los retira |
| Entorno | vía de entrega en Claude Code | cómo recibe Claude Code los hooks: `plugin` o `settings`, según `install-state.json` (en la carpeta de datos, junto a `language.json`). Sin ese fichero es una instalación anterior a la 0.40 y sale `[ -- ]`: `update` la pone al día. Dentro de WSL siempre es `settings` |
| Andamiaje | hooks registrados | entradas **nuestras** en `~/.claude/settings.json` (las ajenas no se cuentan). Con la entrega por **plugin** lo correcto es que **no** haya ninguna: los hooks vienen del plugin, y una nuestra en settings correría dos veces (`[WARN]`, lo arregla `update`) |
| Andamiaje | intérprete de los hooks del plugin | solo con el plugin: que la opción `ld_bin` del plugin (`pluginConfigs` de `~/.claude/settings.json`) exista (`[FALT]` si no) y sea el intérprete del entorno de `uv tool` de **esta** versión (`[WARN]` si apunta a otro). Un `ld_bin` que no existe deja los hooks sin actuar y sin avisar, porque nunca bloquean |
| Andamiaje | hooks duplicados | hooks nuestros en `~/.claude/settings.json` **y** el plugin habilitado a la vez (`enabledPlugins`): cada evento corre dos veces. Pasa si se baja a la 0.39 sin `uninstall` antes. `[WARN]`; `update` retira los de settings |
| Andamiaje | mod del plugin cargado | solo con el plugin: el **latido** que el mod escribe al iniciar cada sesión (`<config>/plugins/data/local-delegate-local-delegate/heartbeats/<sesión>.json`). Toma el más reciente y dice la sesión, la hora, la versión y el estado de cada pieza (`on`, `off`, `absent`, `failed`). `[WARN]` si no hay ninguno (el mod no cargó nunca), si el último tiene más de 7 días, si no se puede leer o si una pieza falló; lo arregla abrir una sesión nueva, y `claude --debug` dice por qué no cargó. Los hooks siguen funcionando aunque el mod no cargue |
| Andamiaje | mod de lectura y hooks de lectura coordinados | solo con el plugin y `read_mod_enabled` encendido (lo está si no se guardó en `false`): que el mod de lectura y un hook de lectura no actúen sobre la misma lectura, y que con la opción encendida alguno actúe. `[WARN]` si quedan hooks de lectura en `~/.claude/settings.json` (no ven la opción del plugin y no se apartan; lo arregla `update`) o si la capa activa del hook de lectura está apagada (el mod no actúa y el hook tampoco; lo arregla `install --enable-read-hook`). Con la opción apagada es `[ OK ]`: actúan los hooks, como en la 0.40 |
| Andamiaje | skill local-delegation | la skill **en cada cliente al que se le escribe**: `~/.claude/skills/local-delegation/SKILL.md` y `~/.config/opencode/skill/local-delegation/`. Mirar solo la de Claude Code daba un `[ OK ]` con la de opencode borrada |
| Andamiaje | memoria global | el bloque entre marcadores en `CLAUDE.md` y `AGENTS.md`, y que sea **el del paquete** (sin contar saltos de línea ni espacios al final). Con otro texto da `warn` («desfasado») y `update` lo repone dejando el `.bak`; también si lo editaste a mano dentro de los marcadores |
| Andamiaje | MCP en Claude Code | la entrada `local-delegate` en `~/.claude.json` |
| Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml`, **también con sangría**: otros programas reescriben ese fichero a su manera (el plugin de JetBrains lo indenta entero y se come los comentarios). Con el marcador de apertura es nuestra y `[ OK ]`, aunque falte el de cierre; sin marcadores, `warn` y no se pisa |
| Andamiaje | MCP en opencode | la clave `mcp.local-delegate` de `~/.config/opencode/opencode.json` **o** `opencode.jsonc` — opencode lee los dos y los fusiona |
| Andamiaje | autocompletado del shell | el de `install --shell-completion`, si está: lee el manifiesto `installed.json` y compara cada fichero con el que genera la versión instalada **en el idioma del manifiesto** (así el veredicto no cambia con el idioma de la sesión), y mira que cada perfil listado siga teniendo el bloque que lo carga. No lanza ningún shell. Sin nada instalado, `[ OK ]` «no instalado (opcional)»; fichero de otra versión o distinto, `warn` con `local-delegate update`; fichero ausente, bloque borrado o ficheros sin manifiesto, `warn` con `local-delegate install --shell-completion`; manifiesto, fichero o perfil ilegible, `unknown` |
| Servicios | daemon | `http://127.0.0.1:9393/api/daemon` (versión y pid), y si sirve una versión **distinta de la instalada** |
| Servicios | backend | `BASE_URL/models` |
| Servicios | credencial del backend | si el proceso MCP que arranca **tu cliente** podrá autenticarse. Pregunta al backend **sin** credencial: si lo rechaza y alguna entrada MCP está en modo `stdio`, ese proceso no la tendrá y sus tools `local_*` responderán `401` — aunque el daemon vea el backend perfectamente |
| Servicios | token del puerto del daemon | la **otra** puerta del mismo camino: si el puerto del daemon exige token, si las entradas MCP en modo `http` lo llevan. Pregunta al puerto y compara con lo que llevan las entradas de los tres clientes; sin cabecera, `warn` nombrando al cliente. Existe porque `install` sin `--web-token-env` deja la entrada sin `Authorization` y el cliente en `401` sin que nada lo dijera |
| Servicios | versión de Claude Code | `claude --version` contra la mínima del plugin (2.1.292); por debajo, `[WARN]` e `install` sigue por settings. Es la versión del **CLI**: la pestaña Code de Claude Desktop y la extensión de VS Code no se pueden medir desde aquí, y piden **2.1.286** y **2.1.299** respectivamente (límite documentado; lo de VS Code no se verificó en vivo). Dentro de WSL no aplica |
| Servicios | plugin de Claude Code | solo con el plugin: `claude plugin list --json` lo lista **instalado** (`[FALT]` si no), **habilitado**, con la **versión del paquete** y con la opción `language` en el idioma vigente (`[WARN]` si no). Dentro de WSL no se espera |
| Servicios | token de Claude Desktop | si la entrada `local-delegate` de Claude Desktop puede entrar al puerto del daemon. Desde la 0.40 la entrada buena es la del **puente** (`local-delegate desktop-bridge`, la escribe `install --desktop` en Windows): se comprueba que su ejecutable exista y se prueba **el token que lee el puente**. Claude Desktop no pasa tu entorno a sus MCP ni expande `${VAR}`, así que una entrada con `${…}` o con el token escrito tal cual (en la cabecera o en su `env`) da `[WARN]` aunque el daemon la acepte, y el token nunca se imprime. Para la entrada antigua de `mcp-remote`: Lee `claude_desktop_config.json` (en Windows, `%APPDATA%\Claude\`), saca la cabecera `Authorization` del `--header` de `mcp-remote` y **prueba ese token** contra el puerto, porque va escrito literal y un token viejo tiene la misma forma que uno bueno. Nunca lo imprime. Sin fichero, sin entrada nuestra, por stdio o apuntando a otra máquina, `unknown`. Existe porque al rotar el token `install` arregla los otros tres clientes y este se quedaba en `401` en silencio |
| Backend | llama-swap | versión instalada vs probada |
| Backend | llama-server | versión instalada vs probada |
| Backend | residencia de llama-swap | la config que usa llama-swap (`--config`, si no `LLAMASWAP_CONFIG` de este shell, si no la que dice el daemon): `[ OK ]` con «sin residente» (lo recomendado); con un residente elegido con `--pin`, también `[ OK ]`, e informa de la VRAM que retiene; `warn` si hay un grupo `persistent` con TTL mayor que 0, porque `persistent` no lo mantiene cargado. Mira también las celdas de la [afinidad](Tools.md#afinidad-usar-el-modelo-que-ya-está-cargado): `warn` («afinidad sin base») si la config apunta a otro GGUF bajo el mismo id en esta máquina, si el modelo del rol cambió por variable o si difiere otra parte de la huella (`-ncmoe`, contexto, tamaño, prompt); en **otra máquina**, donde los GGUF medidos no existen, lo dice en el detalle («afinidad inerte aquí») sin `[WARN]` |
| Backend | turno del daemon | si el daemon reparte el backend por turno entre los modelos que chocan y, si no, por qué (sin `LLAMASWAP_CONFIG`, `matrix`, backend remoto…). Lo pregunta al daemon; si no contesta, lee la config de este shell y lo dice |

Cuatro estados, y la diferencia entre los dos últimos importa:

| Estado | Significa | Cuenta para el exit code |
|---|---|---|
| `[ OK ]` | está y como debe estar | no |
| `[WARN]` | está, pero no como debería (versión vieja, entrada puesta a mano, hooks de una instalación anterior) | sí |
| `[FALT]` | falta de verdad, y la línea de abajo dice qué comando lo arregla | sí |
| `[ -- ]` | **no se pudo comprobar**: el cliente no está instalado, faltan permisos, no hay red, o el backend responde `401` (está arriba y falta la credencial en este entorno) | no |

`[ -- ]` nunca es `[FALT]` a propósito: si un archivo ilegible o un cliente ausente se reportaran
como «falta», un arreglo automático posterior sobrescribiría configuración que no es nuestra. El
exit code es **0** sin avisos y **1** con al menos uno.

De las treinta y cuatro comprobaciones, **«versión publicada» es la única que consulta PyPI**, con un timeout
de dos segundos y degradando a `[ -- ]` si no hay red. Y lo hace **solo en `doctor`**: ni el
reporte de `install` ni el diagnóstico interno de `update` salen a internet por ella —el primero
porque instalar unos hooks no es motivo para hacerlo, y el segundo porque ya pregunta la versión
por su cuenta y sería consultar dos veces lo mismo—.
