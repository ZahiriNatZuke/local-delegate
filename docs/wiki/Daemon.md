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

opencode (`~/.config/opencode/opencode.json`, o su CLI):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "local-delegate": { "type": "remote", "url": "http://127.0.0.1:9393/mcp" }
  }
}
```

```bash
opencode mcp add local-delegate --url http://127.0.0.1:9393/mcp
```

Configura todos los clientes contra la misma URL. El daemon y `llama-swap` quedan como los dos
únicos procesos persistentes relevantes: el primero posee MCP/dashboard/telemetría; el segundo
posee el ciclo de vida y routing de modelos.

El daemon aplica además backpressure global con `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS` (default
`2`). Este límite evita que una ráfaga de clientes cree solicitudes ilimitadas; `llama-swap`
continúa siendo la única fuente de verdad para decidir qué modelos pueden convivir en VRAM.

## Autenticación del puerto

Por defecto el puerto **no pide nada**: el daemon escucha en loopback y exigir credenciales
rompería toda instalación existente. Eso vale mientras el puerto sea solo tuyo.

**Deja de valer en cuanto pones un proxy delante** —un túnel, un nginx, un reenvío de puerto de una
VPN—, y `LOCAL_DELEGATE_WEB_HOST` no se entera: el proxy conecta contra `127.0.0.1` igual que tú,
así que ni esa variable ni la IP de origen delatan que el daemon dejó de ser local. Quien alcance
el puerto puede **delegar con la credencial del backend que tiene el daemon**, y leer el panel y
`/api/*` sin ni siquiera eso.

Para cerrarlo, define la variable en el entorno **del daemon** (donde esté su lanzador o su tarea
programada):

```powershell
$env:LOCAL_DELEGATE_WEB_TOKEN = '<un secreto largo y aleatorio>'
```

Con ella, **todo** el puerto exige el token: el endpoint MCP, el dashboard y `/api/*`. Se acepta de
dos formas, porque hay dos clases de cliente:

| Cómo llega | Quién la usa |
| --- | --- |
| `Authorization: Bearer <token>` | clientes MCP, `curl`, el propio CLI |
| `Authorization: Basic <base64(usuario:token)>` | el navegador, que pide las credenciales solo |

En el navegador, el usuario da igual —solo se compara la contraseña— y basta con pegar el token
donde pide la clave: el 401 lleva `WWW-Authenticate`, así que el diálogo sale sin más.

### Que los clientes sigan funcionando

El token **nunca se escribe en un fichero de configuración**. Se referencia la variable:

```powershell
local-delegate install --mcp-mode http --web-token-env
```

Eso deja a Claude Code con `"headers": {"Authorization": "Bearer ${LOCAL_DELEGATE_WEB_TOKEN}"}`
—que expande al conectar—, a Codex con `bearer_token_env_var = "LOCAL_DELEGATE_WEB_TOKEN"`, que es
la clave que tiene para esto (Codex no expande `${VAR}` en TOML, y de hecho rechaza un token
literal en este transporte), y a opencode con
`"Authorization": "Bearer {env:LOCAL_DELEGATE_WEB_TOKEN}"`, que es **su** sintaxis: opencode no
sustituye `${VAR}`, así que la forma de Claude Code ahí llegaría literal y el backend devolvería
`401`.

Para que funcione, **la variable tiene que existir también en el entorno del cliente**, no solo en
el del daemon. Es el punto donde esto se rompe en silencio: si el cliente no la ve, manda un token
vacío y se lleva un `401` sin más explicación.

El CLI se autentica solo si la variable está en su entorno. Si no la encuentra, `local-delegate
doctor` lo dice con todas las letras —«nuestro daemon escucha en … pero este entorno no tiene su
token»— en vez de acusar al puerto de estar ocupado por otro proceso.

## Inicio de sesión y rollback

El daemon se registra en el gestor de servicios del usuario de cada sistema, con estos **nombres
canónicos** —los mismos que busca `local-delegate update` para reiniciarlo:

| Sistema | Mecanismo | Nombre |
|---|---|---|
| Windows | Tarea programada *AtLogOn* | `LocalDelegateDaemon` |
| macOS | LaunchAgent | `com.local-delegate.daemon` |
| Linux | `systemd --user` | `local-delegate.service` |

Si el nombre no coincide, `update` no encuentra el servicio y cae al fallback (terminar el proceso
y relanzar `serve` desacoplado), que funciona pero deja el arranque automático sin usar. El comando
debe ejecutarse en **primer plano** dentro del gestor; no hace falta que `local-delegate` se
daemonice a sí mismo.

### Windows sin ventana visible

Una tarea marcada como `Hidden` queda oculta en el Programador de tareas, pero un ejecutable de
consola aún puede mostrar una ventana. Hay dos casos según necesites o no descifrar un secreto.

**Caso simple (sin backend autenticado).** Usa el `pythonw.exe` del entorno donde está instalado
`local-delegate`. Al pertenecer al subsistema GUI, nunca crea consola:

```powershell
$pythonw = 'C:\ruta\al\entorno\Scripts\pythonw.exe'
$action = New-ScheduledTaskAction `
  -Execute $pythonw `
  -Argument '-m local_delegate serve --log-level warning' `
  -WorkingDirectory 'C:\ruta\al\workspace'
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'LocalDelegateDaemon' -Action $action `
  -Trigger $trigger -Settings $settings -Description 'Daemon MCP local compartido' -Force
```

**Caso con secreto DPAPI.** Si el backend está autenticado, la acción ya no puede ser `pythonw`
directo: hace falta un launcher de PowerShell que importe el `SecureString` antes de arrancar el
daemon (ver [Remote-backend](Remote-backend.md)). Ese launcher **reintroduce la ventana**, y
`-WindowStyle Hidden` no la evita:

- `powershell.exe` pertenece al subsistema de consola, así que Windows le crea una consola al
  lanzarlo en una tarea con `LogonType = InteractiveToken`.
- En Windows 11 el terminal por defecto («Que Windows decida», `DelegationConsole` /
  `DelegationTerminal` a GUID nulo en `HKCU:\Console\%%Startup`) es Windows Terminal, que **ignora
  la petición `SW_HIDE`** al recibir el *handoff* de la consola. La ventana aparece igual, titulada
  con la ruta cruda del `.exe`.
- `Settings.Hidden` no interviene: solo oculta la tarea en la lista del Programador.

La solución es envolver el launcher en `conhost --headless`, que crea un pseudoconsole sin ventana:

```powershell
$ps1exe  = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$conhost = "$env:SystemRoot\System32\conhost.exe"
$arg = '--headless ' + $ps1exe +
       ' -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\ruta\al\launcher.ps1"'
$action = New-ScheduledTaskAction -Execute $conhost -Argument $arg `
  -WorkingDirectory 'C:\ruta\al\workspace'
Set-ScheduledTask -TaskName 'LocalDelegateDaemon' -Action $action
```

Mantén `LogonType = InteractiveToken`. La alternativa de pasar la tarea a «ejecutar tanto si el
usuario inició sesión como si no» también elimina la ventana —corre en la sesión 0—, pero solo
sirve guardando la contraseña de la cuenta: la variante S4U no desbloquea el master key DPAPI del
usuario y el `Import-Clixml` del launcher falla.

Si el launcher hace `WaitForExit()` sobre el daemon, la ventana no era un parpadeo sino
persistente. Al cerrarla a mano el daemon sobrevive huérfano, pero la tarea registra
`LastTaskResult = 0xC000013A` (`STATUS_CONTROL_C_EXIT`); es la firma de este problema.

La tarea es de **Windows a nivel del usuario**. No pertenece a Codex ni a Claude Code: se inicia
una vez al entrar en Windows y atiende a todos los clientes por la misma URL. `IgnoreNew` y el lock
interno del daemon son dos defensas contra instancias duplicadas.

### macOS: LaunchAgent

El label **debe** ser `com.local-delegate.daemon`. Guarda esto en
`~/Library/LaunchAgents/com.local-delegate.daemon.plist`, sustituyendo las dos rutas:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local-delegate.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ruta/al/entorno/bin/python3</string>
    <string>-m</string>
    <string>local_delegate</string>
    <string>serve</string>
    <string>--log-level</string>
    <string>warning</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/local-delegate.log</string>
  <key>StandardErrorPath</key>
  <string>/tmp/local-delegate.err</string>
</dict>
</plist>
```

Se carga y se comprueba así:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local-delegate.daemon.plist
launchctl print gui/$(id -u)/com.local-delegate.daemon   # lo que consulta `update`
```

Para reiniciarlo a mano, el mismo comando que usa `update`:

```bash
launchctl kickstart -k gui/$(id -u)/com.local-delegate.daemon
```

`KeepAlive` hace que launchd lo reponga si muere. Si el backend está autenticado, la key no puede
ir en el plist: exporta la variable desde un script envoltorio y apunta `ProgramArguments` a él.

### Linux: `systemd --user`

La unidad **debe** llamarse `local-delegate.service`. En
`~/.config/systemd/user/local-delegate.service`:

```ini
[Unit]
Description=Daemon MCP local compartido (local-delegate)
After=network.target

[Service]
Type=simple
ExecStart=/ruta/al/entorno/bin/python3 -m local_delegate serve --log-level warning
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now local-delegate.service
systemctl --user cat local-delegate.service    # lo que consulta `update`
systemctl --user restart local-delegate.service
```

Si el daemon tiene que sobrevivir al cierre de sesión, habilita *lingering* para tu usuario con
`loginctl enable-linger $USER`; sin eso systemd cierra los servicios de usuario al salir.

### Qué significa «DAEMON MCP» en el dashboard

La tabla «Procesos del backend» muestra el daemon, `llama-swap` y los procesos `llama-server`
detectados. La insignia `DAEMON MCP` marca el proceso servidor compartido; debe existir una sola
fila con esa insignia. No cuenta sesiones de Codex/Claude ni conexiones HTTP. Una sesión nueva no
debe crear otra fila: solo abre otra conexión al mismo daemon.

Rollback: detén el servicio/tarea y restaura en cada cliente el bloque `command`/`args` de `stdio`:

```json
{"command":"uvx","args":["local-delegate-mcp"]}
```

El modo `stdio` continúa soportado; no depende del daemon HTTP.
