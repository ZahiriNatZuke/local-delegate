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
| Entrada MCP | Claude Code (`claude mcp add-json --scope user`, o `~/.claude.json` si no está la CLI) y `~/.codex/config.toml` | `stdio` con `uvx` por defecto; `--mcp-mode http` apunta al daemon compartido |
| Hooks | `~/.claude/hooks/local-delegate/` + registro en `~/.claude/settings.json` | `UserPromptSubmit` y `PreToolUse`/`Bash`; el de `Read` solo con `--enable-read-hook` |
| Skill | `~/.claude/skills/delegacion-local/SKILL.md` | regla de oro + catálogo de tools |
| Memoria | bloque entre marcadores en `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md` | resumen corto de la regla, siempre cargado |

## A quién configura

Por defecto (`--clients auto`), **solo los clientes que están instalados**: se mira si existen
`~/.claude` y `~/.codex`. En una máquina con un solo cliente ya no se crea el directorio del
otro, que era lo que pasaba con el antiguo default `--target all`.

```bash
local-delegate install                      # los que estén instalados
local-delegate install --clients codex      # ese, exista o no (orden explícita)
local-delegate install --target all         # los dos, como antes
```

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
  (`${LOCAL_DELEGATE_API_KEY}` en Claude Code, `env_vars` en Codex): la key nunca se escribe.
- **Reversible.** `uninstall` borra los directorios propios y quita solo sus entradas.

## Opciones

| Flag | Efecto |
|---|---|
| `--dry-run` | describe los cambios sin escribir nada |
| `--clients auto \| claude \| codex` | cliente(s) a configurar (repetible; default `auto`) |
| `--force-mcp-codex` | reemplaza sin preguntar una entrada de Codex escrita a mano |
| `--target claude \| codex \| all` | histórico, equivale a `--clients`; `all` fuerza los dos aunque no estén instalados. No se combina con `--clients` |
| `--no-hooks` / `--no-skill` / `--no-memory` / `--no-mcp` | excluye ese componente |
| `--enable-read-hook` | registra también el experimental `PreToolUse`/`Read` |
| `--mcp-mode stdio\|http` | proceso por sesión (`uvx`) o daemon compartido en `/mcp` |
| `--base-url URL` | fija `LOCAL_DELEGATE_BASE_URL` en la entrada MCP (backend remoto) |
| `--api-key-env` | reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno |
| `--pin-version X.Y.Z` | fija la versión del paquete en la entrada MCP |
| `--python RUTA` | intérprete con el que corren los hooks (default `python3`, `python` en Windows) |
| `--home RUTA` | HOME alternativo (útil para probar la instalación en un sandbox) |
| `--no-client-cli` | no usar el binario `claude`; edita `~/.claude.json` directamente |

El intérprete por defecto **no** es el que ejecuta el instalador: bajo `uvx` ese vive en un
entorno efímero que desaparece al terminar el comando y dejaría los hooks apuntando a una ruta
inexistente.

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

- `local-delegate doctor` → comprueba de una vez las doce piezas (ver abajo), incluidos el
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
| Entorno | clientes | si existen `~/.claude` y `~/.codex` |
| Andamiaje | hooks copiados | los scripts en `~/.claude/hooks/local-delegate/` |
| Andamiaje | hooks registrados | entradas **nuestras** en `~/.claude/settings.json` (las ajenas no se cuentan) |
| Andamiaje | skill | `~/.claude/skills/delegacion-local/SKILL.md` |
| Andamiaje | memoria global | el bloque entre marcadores en `CLAUDE.md` y `AGENTS.md` |
| Andamiaje | MCP en Claude Code | la entrada `local-delegate` en `~/.claude.json` |
| Andamiaje | MCP en Codex | la sección `[mcp_servers.local-delegate]` de `~/.codex/config.toml` |
| Servicios | daemon | `http://127.0.0.1:9393/api/daemon` (versión y pid), y si sirve una versión **distinta de la instalada** |
| Servicios | backend | `BASE_URL/models` |
| Backend | llama-swap | versión instalada vs probada |
| Backend | llama-server | versión instalada vs probada |

Cuatro estados, y la diferencia entre los dos últimos importa:

| Estado | Significa | Cuenta para el exit code |
|---|---|---|
| `[ OK ]` | está y como debe estar | no |
| `[WARN]` | está, pero no como debería (versión vieja, entrada puesta a mano, hooks de una instalación anterior) | sí |
| `[FALT]` | falta de verdad, y la línea de abajo dice qué comando lo arregla | sí |
| `[ -- ]` | **no se pudo comprobar**: el cliente no está instalado, faltan permisos, o el backend responde `401` (está arriba y falta la credencial en este entorno) | no |

`[ -- ]` nunca es `[FALT]` a propósito: si un archivo ilegible o un cliente ausente se reportaran
como «falta», un arreglo automático posterior sobrescribiría configuración que no es nuestra. El
exit code es **0** sin avisos y **1** con al menos uno.
