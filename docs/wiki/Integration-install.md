# Instalación de la integración (`install` / `uninstall`)

Instalar el MCP nunca fue solo registrar el servidor: las tools se usan de verdad cuando el
cliente además tiene los **hooks**, la **skill** y la **regla en memoria**. `local-delegate
install` deja las cuatro piezas puestas de una vez, de forma idempotente y reversible.

```bash
uvx local-delegate-mcp install --dry-run   # muestra cada cambio, sin escribir
uvx local-delegate-mcp install             # aplica
uvx local-delegate-mcp uninstall           # revierte solo lo que instaló
```

## Qué instala

| Componente | Destino | Notas |
|---|---|---|
| Entrada MCP | Claude Code (`claude mcp add-json --scope user`, o `~/.claude.json` si no está la CLI) y `~/.codex/config.toml` | `stdio` con `uvx` por defecto; `--mcp-mode http` apunta al daemon compartido |
| Hooks | `~/.claude/hooks/local-delegate/` + registro en `~/.claude/settings.json` | `UserPromptSubmit` y `PreToolUse`/`Bash`; el de `Read` solo con `--enable-read-hook` |
| Skill | `~/.claude/skills/delegacion-local/SKILL.md` | regla de oro + catálogo de tools |
| Memoria | bloque entre marcadores en `~/.claude/CLAUDE.md` y `~/.codex/AGENTS.md` | resumen corto de la regla, siempre cargado |

## Garantías

- **Idempotente.** Los bloques de Markdown/TOML van entre marcadores `local-delegate:begin/end`
  y se reemplazan, nunca se duplican; los hooks se desregistran antes de volver a registrarse.
- **No pisa nada ajeno.** Los hooks de terceros, el resto de `settings.json`, el resto de tu
  `CLAUDE.md` y las otras entradas de `config.toml` se conservan intactos.
- **Backups.** Cada archivo compartido que se edita deja un `.bak` al lado.
- **Sin secretos.** `--api-key-env` reenvía `LOCAL_DELEGATE_API_KEY` desde el entorno
  (`${LOCAL_DELEGATE_API_KEY}` en Claude Code, `env_vars` en Codex): la key nunca se escribe.
- **Reversible.** `uninstall` borra los directorios propios y quita solo sus entradas.

## Opciones

| Flag | Efecto |
|---|---|
| `--dry-run` | describe los cambios sin escribir nada |
| `--target claude \| codex \| all` | cliente(s) a configurar (repetible; default `all`) |
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
  --pin-version 0.11.0
```

Los `path` se siguen leyendo en la Mac (que es lo que conserva el ahorro de contexto) y el
dashboard marcará esas delegaciones como **cómputo remoto**. Ver
[Backend remoto Mac → PC](./Remote-backend.md).

## Después de instalar

Reinicia el cliente. Verifica con:

- `local_status` → backend, catálogo y si el cómputo es local o remoto.
- Un prompt tipo "resume este archivo en cinco viñetas" → debe aparecer la sugerencia del hook.
- `http://127.0.0.1:9393` → panel de ahorro.
