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
| Hooks | `~/.claude/hooks/local-delegate/` + registro en `~/.claude/settings.json` | `UserPromptSubmit` y `PreToolUse`/`Bash`; el de `Read` solo con `--enable-read-hook`, que lo deja activo |
| Skill | `~/.claude/skills/delegacion-local/SKILL.md` y `~/.config/opencode/skill/delegacion-local/SKILL.md` | regla de oro + catálogo de tools |
| Memoria | bloque entre marcadores en `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md` y `~/.config/opencode/AGENTS.md` | resumen corto de la regla, siempre cargado |

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
- **Backups.** Cada archivo compartido que se edita deja un `.bak` al lado.
- **Sin secretos.** `--api-key-env` reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno
  (`${LOCAL_DELEGATE_API_KEY}` en Claude Code, `env_vars` en Codex, `{env:LOCAL_DELEGATE_API_KEY}`
  en opencode — cada uno tiene su sintaxis y la del otro **no** se expande): la key nunca se escribe.
- **Con opencode, no se pisa un fichero que lleve comentarios.** Su configuración es JSONC y
  admite comentarios aunque el fichero se llame `.json`; reescribirla con un serializador de JSON
  los borraría **sin que el fichero pareciera roto**. Por eso el camino normal es su propia CLI
  (`opencode mcp add`, que los conserva), y cuando esa CLI no está y el fichero tiene comentarios
  —o no se puede parsear— la entrada MCP **no se escribe**: se avisa con la ruta y se sigue con el
  resto de componentes. Instalar la CLI de opencode y repetir el `install` lo resuelve.
- **En opencode nunca se escribe una clave que no sea `mcp`.** Una clave de primer nivel
  desconocida hace que opencode **no arranque** (`ConfigInvalidError`), así que ahí no hay
  marcadores `local-delegate:begin/end`: la entrada se identifica por su nombre, como en Claude
  Code. Consecuencia: en opencode no hay pregunta previa equivalente a `--force-mcp-codex`, porque
  no hay forma de distinguir una entrada nuestra de una que escribiste tú.
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
| `--enable-read-hook` | registra **y enciende** el experimental `PreToolUse`/`Read`. Antes solo lo registraba: el script exigía además `LD_HOOK_READ_ENABLED=1` y la bandera no encendía nada |
| `--mcp-mode stdio\|http` | proceso por sesión (`uvx`) o daemon compartido en `/mcp`. **Si tu backend exige API key, `http` suele ser la única opción que funciona**: el proceso `stdio` lo lanza el cliente y hereda *su* entorno, no el del lanzador del daemon, que es quien tiene el secreto. Lo avisa el check «credencial del backend» |
| `--base-url URL` | fija `LOCAL_DELEGATE_BASE_URL` en la entrada MCP (backend remoto) |
| `--api-key-env` | reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno |
| `--pin-version X.Y.Z` | fija la versión del paquete en la entrada MCP |
| `--python RUTA` | intérprete con el que corren los hooks (default `python3`, `python` en Windows) |
| `--home RUTA` | HOME alternativo (útil para probar la instalación en un sandbox) |
| `--no-client-cli` | no usar el binario `claude`; edita `~/.claude.json` directamente |

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
4. **Cada fichero modificado deja su `.bak`.**

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

- `local-delegate doctor` → comprueba de una vez las dieciséis piezas (ver abajo), incluidos el
  daemon y el backend, que el reporte de `install` no mira a propósito.
- `local_status` → backend, catálogo y si el cómputo es local o remoto.
- Un prompt tipo "resume este archivo en cinco viñetas" → debe aparecer la sugerencia del hook.
- `http://127.0.0.1:9393` → panel de ahorro.

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
| Andamiaje | hooks copiados | los scripts en `~/.claude/hooks/local-delegate/` |
| Andamiaje | hooks huérfanos | scripts nuestros sueltos en `~/.claude/hooks/` que dejó una instalación anterior; `install` los retira |
| Andamiaje | hooks registrados | entradas **nuestras** en `~/.claude/settings.json` (las ajenas no se cuentan) |
| Andamiaje | skill | `~/.claude/skills/delegacion-local/SKILL.md` |
| Andamiaje | memoria global | el bloque entre marcadores en `CLAUDE.md` y `AGENTS.md` |
| Andamiaje | MCP en Claude Code | la entrada `local-delegate` en `~/.claude.json` |
| Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml` |
| Andamiaje | MCP en opencode | la clave `mcp.local-delegate` de `~/.config/opencode/opencode.json` **o** `opencode.jsonc` — opencode lee los dos y los fusiona |
| Servicios | daemon | `http://127.0.0.1:9393/api/daemon` (versión y pid), y si sirve una versión **distinta de la instalada** |
| Servicios | backend | `BASE_URL/models` |
| Servicios | credencial del backend | si el proceso MCP que arranca **tu cliente** podrá autenticarse. Pregunta al backend **sin** credencial: si lo rechaza y alguna entrada MCP está en modo `stdio`, ese proceso no la tendrá y sus tools `local_*` responderán `401` — aunque el daemon vea el backend perfectamente |
| Backend | llama-swap | versión instalada vs probada |
| Backend | llama-server | versión instalada vs probada |

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

De las trece comprobaciones, **«versión publicada» es la única que consulta PyPI**, con un timeout
de dos segundos y degradando a `[ -- ]` si no hay red. Y lo hace **solo en `doctor`**: ni el
reporte de `install` ni el diagnóstico interno de `update` salen a internet por ella —el primero
porque instalar unos hooks no es motivo para hacerlo, y el segundo porque ya pregunta la versión
por su cuenta y sería consultar dos veces lo mismo—.
