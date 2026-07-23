# Daemon compartido

## Por qué existe

El transporte MCP `stdio` requiere un proceso por cliente o sesión. Eso es compatible y simple,
pero el dashboard embebido vive y muere con el proceso que ganó el puerto `9393`. Si ese proceso
termina, las demás instancias `stdio` no reclaman el puerto.

`local-delegate serve` evita ese ciclo de vida efímero: mantiene un único proceso por usuario que
sirve MCP Streamable HTTP y el dashboard juntos.

```text
Codex ───────┐
Claude Code ─┼── HTTP /mcp ──▶ local-delegate daemon ──▶ backend OpenAI-compatible
otro cliente ┘                       │
                                    └── dashboard /
```

## Arranque

```powershell
uvx local-delegate-mcp serve
```

Defaults:

- MCP: `http://127.0.0.1:9393/mcp`
- Dashboard: `http://127.0.0.1:9393/`
- Estado: `http://127.0.0.1:9393/api/daemon`
- Lock/estado: directorio de datos del usuario (`daemon.lock` / `daemon.json`)

`--host`, `--port` y `--log-level` permiten cambiar la escucha. Mantén `127.0.0.1` salvo que
hayas diseñado autenticación y firewall para exponerlo: el daemon no debe publicarse en la LAN.

Las variables de entorno de backend/modelos deben pertenecer al **proceso daemon**, no a cada
cliente. Por ejemplo, para autoarrancar llama-swap:

```powershell
$env:LOCAL_DELEGATE_AUTOSTART='1'
$env:LLAMASWAP_EXE='D:\ruta\llama-swap.exe'
$env:LLAMASWAP_CONFIG='D:\ruta\config.yaml'
$env:LLAMASWAP_WATCH_CONFIG='1'
uvx local-delegate-mcp serve
```

## Clientes

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.local-delegate]
url = "http://127.0.0.1:9393/mcp"
```

Claude Code:

```powershell
claude mcp add --transport http --scope user local-delegate http://127.0.0.1:9393/mcp
```

Configura todos los clientes contra la misma URL. El daemon y `llama-swap` quedan como los dos
únicos procesos persistentes relevantes: el primero posee MCP/dashboard/telemetría; el segundo
posee el ciclo de vida y routing de modelos.

## Inicio de sesión y rollback

En Windows puede registrarse `local-delegate serve` como tarea *AtLogOn*. En Linux/macOS usa el
gestor de servicios del usuario (`systemd --user`, `launchd`, etc.). El comando debe ejecutarse en
primer plano dentro del gestor; no hace falta que `local-delegate` se daemonice a sí mismo.

Rollback: detén el servicio/tarea y restaura en cada cliente el bloque `command`/`args` de `stdio`:

```json
{"command":"uvx","args":["local-delegate-mcp"]}
```

El modo `stdio` continúa soportado; no depende del daemon HTTP.
