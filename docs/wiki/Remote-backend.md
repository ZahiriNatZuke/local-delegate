# Backend remoto Mac → PC

La configuración recomendada ejecuta el MCP en la Mac y solo manda inferencia al llama-swap de la
PC. Así `local_summarize(path="/Users/...")` abre el archivo en la Mac y conserva el ahorro de
contexto; un MCP ejecutado entero en Windows no puede abrir ese path.

```text
Codex/Claude (Mac) -> local-delegate 0.14.0 (Mac) -> HTTPS privado -> llama-swap (PC) -> GPU
```

## Requisitos ya listos en la PC

- llama-swap escucha en loopback y exige `apiKeys` mediante una variable de entorno.
- Tailscale Serve publica `9292` y `9393` solo dentro del tailnet; Funnel y puertos del router
  permanecen cerrados.
- La policy permite que la Mac llegue a esos puertos.
- La Mac guardó la misma key con servicio Keychain `local-delegate-remote`.

Define una sola vez el nombre MagicDNS de la PC y deja que el resto de los comandos reutilice la
URL:

```bash
export PC_MAGICDNS="PC_MAGICDNS"
export LOCAL_DELEGATE_BASE_URL="https://${PC_MAGICDNS}:9292/v1"
export LOCAL_DELEGATE_AUTOSTART="0"
export LOCAL_DELEGATE_API_KEY="$(security find-generic-password \
  -a "$USER" -s local-delegate-remote -w)"

curl --fail --max-time 5 \
  -H "Authorization: Bearer $LOCAL_DELEGATE_API_KEY" \
  "$LOCAL_DELEGATE_BASE_URL/models"
```

Debe devolver JSON de modelos. `401` significa key ausente/incorrecta; timeout significa ruta,
grant o Serve; error DNS significa MagicDNS.

## Carga automática desde Keychain

Este bloque deja la URL y la lectura segura de Keychain en `~/.zshrc`. No guarda la key en texto
plano y evita repetir los `export` en cada terminal:

```bash
touch "$HOME/.zshrc"
python3 - <<'PY'
import os
import re
from pathlib import Path

path = Path.home() / ".zshrc"
text = path.read_text() if path.exists() else ""
text = re.sub(
    r"(?ms)^# local-delegate remote begin\n.*?^# local-delegate remote end\n?",
    "",
    text,
)
base_url = os.environ["LOCAL_DELEGATE_BASE_URL"]
block = f'''# local-delegate remote begin
export LOCAL_DELEGATE_BASE_URL="{base_url}"
export LOCAL_DELEGATE_AUTOSTART="0"
export LOCAL_DELEGATE_API_KEY="$(security find-generic-password -a \"$USER\" -s local-delegate-remote -w 2>/dev/null)"
# local-delegate remote end
'''
path.write_text(text.rstrip() + "\n\n" + block)
PY
source "$HOME/.zshrc"
```

## Credenciales en el Llavero (Claude Code y Claude Desktop)

El bloque de `~/.zshrc` de arriba solo llega a lo que arranca desde una terminal. Claude Desktop
abierto desde el Dock recibe únicamente el entorno de launchd, y una sesión de Claude Code lanzada
desde Desktop hereda el de tu shell de login solo si Desktop consigue resolverlo a tiempo (cuando
no, su log dice `Shell environment extraction timed out`). Sin la variable, el MCP mandaba la
petición sin clave y el backend contestaba `401` en silencio (issue #409).

Desde la 0.41.0 el MCP, el daemon (LaunchAgent) y el mod del plugin buscan cada credencial en
este orden: **la variable de entorno y, si falta, el Llavero**. Guarda las dos una vez:

| Credencial | Variable | Servicio del Llavero |
| --- | --- | --- |
| Clave del backend (llama-swap de la PC) | `LOCAL_DELEGATE_API_KEY` | `local-delegate-remote` |
| Token del puerto del daemon (mod, panel) | `LOCAL_DELEGATE_WEB_TOKEN` | `local-delegate-web-token` |

```bash
security add-generic-password -U -a "$USER" -s local-delegate-remote -w
security add-generic-password -U -a "$USER" -s local-delegate-web-token -w   # si el daemon usa token
```

`-w` al final hace que `security` pida el valor por teclado (no queda en el historial); `-U` lo
sustituye si ya estaba. Para comprobar que está **sin imprimirlo**:

```bash
security find-generic-password -a "$USER" -s local-delegate-remote >/dev/null && echo KEYCHAIN_OK
```

Cómo se comporta:

- La consulta es `/usr/bin/security find-generic-password -a "$USER" -s <servicio> -w`, con ruta
  absoluta (el `PATH` de launchd es mínimo) y un tope de **3 s**: con el Llavero bloqueado,
  `security` puede quedarse esperando un diálogo, y colgar el MCP sería peor que el `401`. Si
  macOS pregunta si permites el acceso, elige «Permitir siempre».
- Se pregunta **una vez por proceso**, también cuando no hay nada. Si guardas o cambias el valor,
  reinicia el cliente (o `launchctl kickstart -k gui/$(id -u)/com.local-delegate.daemon` para el
  daemon).
- El valor no se registra, no se imprime y no se escribe en ningún fichero.
- `local-delegate doctor` dice de dónde sale la clave: `[ OK ]` con «sale del Llavero» o «está en
  el entorno y en el Llavero», y `[WARN]` con el comando `security add-generic-password …` cuando
  **solo** está en el entorno del shell que corre `doctor`, que es justo el caso que una app
  gráfica no ve.
- Límite: la entrada `--mcp-mode http` de Claude Code manda `Bearer ${LOCAL_DELEGATE_WEB_TOKEN}`, y
  eso lo expande Claude Code con su propio entorno, no con el Llavero. La entrada `stdio` de esta
  página no tiene ese problema: el proceso MCP lee la clave él mismo.

El LaunchAgent `remote-env` de [Codex en la Mac](#codex-en-la-mac) sigue siendo la receta para
Codex, que no lee el Llavero; Claude Code y Claude Desktop no lo necesitan.

## Actualizar la Mac tras una release

Como la entrada lleva la versión fijada, cada release nueva pide cambiar el pin. Lo hace el propio
CLI:

```bash
local-delegate update --dry-run   # enseña qué cambiaría, sin escribir nada
local-delegate update             # aplica y deja el daemon arriba
```

Revisa el estado real de la máquina con las mismas comprobaciones que `doctor`, actualiza el pin
donde exista, completa la configuración que falte y termina dejando el daemon arriba: lo reinicia si
corría, lo levanta si no. Es idempotente.

Eso incluye **los hooks de Claude Code**: si los de `~/.claude/hooks/local-delegate/` no son los del
paquete instalado, los repone, y deja el hook de lectura como estaba —registrado si lo estaba, fuera
si no—. Hasta la 0.31.1 no lo hacía: miraba solo que los ficheros existieran, así que tras actualizar
el paquete seguían corriendo los hooks de la versión con la que se hizo el último `install`. El backend de inferencia **no se toca** salvo que lo pidas
con `--restart-backend`, porque reiniciar llama-swap descargaría los modelos de la VRAM.

**Lo que `update` NO hace: actualizar el propio CLI si lo instalaste con `uv tool`.** Te lo dice al
terminar, con el comando:

```bash
uv tool upgrade local-delegate-mcp
```

No lo ejecuta él, y no es pereza: `uv tool` reinstala el entorno entero, que es **el mismo desde el
que `update` se está ejecutando**. Probado en Windows, la reinstalación falla al borrar `Scripts/`
—el proceso lo tiene bloqueado— *después* de haber borrado el paquete, así que deja la instalación
rota: `uv tool list` pasa a decir «Failed find package» y el ejecutable revienta. Por eso el
segundo paso lo das tú, desde otra terminal.

Después, reinicia Claude Code y Codex; el paquete se descarga solo al arrancar el cliente.

**Por qué esto vive en el CLI y no en `scripts/`.** Antes había un `scripts/update_to_latest.sh` que
nunca llegó a hacer este trabajo: el paquete publicado no empaqueta `scripts/`, así que el script no
estaba en la máquina que tenía que actualizarse. La regla que salió de ahí vale para todo el
repositorio — **lo que ejecuta el usuario va al CLI; lo que ejecuta el repositorio se queda en
`scripts/`**, que además ya ni siquiera se publica (ver `Repo-hardening.md`).

## Claude Code en la Mac

La entrada se fija a la versión actual durante el rollout. **Fija la actual, no una vieja**: un pin congela también los rangos de dependencias de aquel wheel, y las anteriores a la 0.12.2 pedían `mcp` sin techo, así que hoy mueren en el import. La key no se pega en el JSON: Claude expande la
variable que cargaste desde Keychain al iniciar la sesión y, si no la tiene (Claude Code lanzado
sin tu shell), el MCP la lee él mismo del Llavero (ver
[Credenciales en el Llavero](#credenciales-en-el-llavero-claude-code-y-claude-desktop)).

```bash
claude mcp remove local-delegate 2>/dev/null || true
claude mcp add-json --scope user local-delegate "$(cat <<JSON
{
  \"type\": \"stdio\",
  \"command\": \"uvx\",
  \"args\": [
    \"--from\",
    \"local-delegate-mcp==0.14.0\",
    \"local-delegate-mcp\"
  ],
  \"env\": {
    \"LOCAL_DELEGATE_BASE_URL\": \"$LOCAL_DELEGATE_BASE_URL\",
    \"LOCAL_DELEGATE_AUTOSTART\": \"0\",
    \"LOCAL_DELEGATE_API_KEY\": \"\${LOCAL_DELEGATE_API_KEY}\"
  }
}
JSON
)"
claude mcp get local-delegate
claude
```

## Codex en la Mac

El bloque siguiente conserva el resto de `~/.codex/config.toml`, reemplaza solo la entrada
`local-delegate` y reenvía la key desde el entorno con `env_vars`; no escribe su valor en TOML:

```bash
mkdir -p "$HOME/.codex"
python3 - <<'PY'
import json
import os
import re
from pathlib import Path

path = Path.home() / ".codex" / "config.toml"
text = path.read_text() if path.exists() else ""
pattern = r"(?ms)^\[mcp_servers\.local-delegate(?:\.[^]]+)?\]\n.*?(?=^\[|\Z)"
text = re.sub(pattern, "", text).rstrip()
base_url = json.dumps(os.environ["LOCAL_DELEGATE_BASE_URL"])
block = f'''[mcp_servers.local-delegate]
command = "uvx"
args = ["--from", "local-delegate-mcp==0.14.0", "local-delegate-mcp"]
env_vars = ["LOCAL_DELEGATE_API_KEY"]

[mcp_servers.local-delegate.env]
LOCAL_DELEGATE_BASE_URL = {base_url}
LOCAL_DELEGATE_AUTOSTART = "0"
'''
path.write_text((text + "\n\n" if text else "") + block)
PY
codex mcp list
```

Reinicia Codex después de guardar la entrada. Codex CLI, la app y la extensión comparten
`config.toml`. Para CLI basta abrir una terminal nueva. Si abres la app desde el Dock, instala una
vez este LaunchAgent (solo para Codex: Claude Code y Claude Desktop leen el Llavero ellos mismos): obtiene la key desde Keychain al iniciar sesión y la deja en el entorno de
las aplicaciones, sin escribirla en disco.

```bash
mkdir -p "$HOME/.local/bin" "$HOME/Library/LaunchAgents"
cat > "$HOME/.local/bin/local-delegate-remote-env.zsh" <<EOF
#!/bin/zsh
token="\$(/usr/bin/security find-generic-password -a "\$USER" -s local-delegate-remote -w 2>/dev/null)" || exit 0
[[ -n "\$token" ]] || exit 0
/bin/launchctl setenv LOCAL_DELEGATE_API_KEY "\$token"
/bin/launchctl setenv LOCAL_DELEGATE_BASE_URL "$LOCAL_DELEGATE_BASE_URL"
/bin/launchctl setenv LOCAL_DELEGATE_AUTOSTART "0"
EOF
chmod 700 "$HOME/.local/bin/local-delegate-remote-env.zsh"
cat > "$HOME/Library/LaunchAgents/com.local-delegate.remote-env.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local-delegate.remote-env</string>
  <key>ProgramArguments</key><array>
    <string>$HOME/.local/bin/local-delegate-remote-env.zsh</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.local-delegate.remote-env.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.local-delegate.remote-env.plist"
launchctl kickstart -k "gui/$(id -u)/com.local-delegate.remote-env"
test -n "$(launchctl getenv LOCAL_DELEGATE_API_KEY)" && echo "CODEX_GUI_KEY_OK"
```

## Turno común PC+Mac

Desde la versión que trae el turno remoto, las operaciones de la Mac y las de la PC hacen **una
sola cola** en el daemon de la PC. Antes cada máquina iba por su lado: la Mac mandaba directo a
`:9292` y, si la PC estaba con otro modelo, llama-swap lo cambiaba a mitad de una operación de la
PC (o la operación de la PC se quedaba esperando dentro de llama-swap hasta el `read_timeout`).

```text
Mac: operación ──▶ POST /api/turn/acquire (daemon de la PC, :9393) ──▶ latido cada 5 s ──▶ :9292 ──▶ release
PC:  operación ──▶ turno local ─────────────── mismo turno.Turn ─────────────────────────▶ :9292
```

Cómo funciona:

- **Qué pide la Mac.** Antes de cada operación (y en cada salto a otro modelo), el proceso de la
  Mac pide turno al daemon de la PC con `POST /api/turn/acquire`. Entra al final de la misma cola
  que las operaciones de la PC, con un **arrendamiento** que mantiene con un latido
  (`/api/turn/heartbeat`, cada `heartbeat_s` que dice el daemon: un tercio de
  `LOCAL_DELEGATE_TURN_LEASE_S`, 5 s como mucho) y suelta al terminar (`/api/turn/release`),
  también si la llamada se cancela o falla. Si la Mac deja de latir, el arrendamiento caduca a los
  `LOCAL_DELEGATE_TURN_LEASE_S` (30 s) y lo que esperaba detrás sigue.
- **Cesión.** Si una operación de la Mac tiene el turno desde hace `LOCAL_DELEGATE_TURN_YIELD_S`
  y bloquea a otra que lleva lo mismo esperando, el daemon le contesta `yield` y la Mac lo suelta
  antes de su siguiente trozo, igual que una operación local.
- **Visible en la PC.** Mientras vive, cada arrendamiento tiene su entrada en «En curso» del panel
  de la PC y en `/api/inflight`, con la máquina (`host`, `host_via: "lease"`) y su estado (en cola,
  procesando o esperando al backend). El daemon de la PC **no** escribe evento de uso por una
  operación de la Mac: la registra solo el log de la Mac (sin doble cuenta).
- **Mientras espera**, el progreso de la llamada en la Mac dice «esperando turno en <máquina>», y la
  espera respeta `LOCAL_DELEGATE_QUEUE_MAX_WAIT_S` igual que en local.

### Configuración por máquina

| Máquina | Qué hace falta | Variables |
|---|---|---|
| PC (daemon con el backend) | El daemon de la versión nueva y **un secreto** en su entorno: la clave del backend (`LOCAL_DELEGATE_API_KEY`, la que exige llama-swap) o el token del puerto (`LOCAL_DELEGATE_WEB_TOKEN`). Sin ninguno, el endpoint responde `403 turn_needs_secret` | `LOCAL_DELEGATE_TURN_SERVER` (`on`), `LOCAL_DELEGATE_TURN_LEASE_S` (30), `LOCAL_DELEGATE_TURN_MAX_LEASES` (16), `LOCAL_DELEGATE_TURN_YIELD_S` (120) |
| Mac (cliente con backend remoto) | Nada nuevo: con `LOCAL_DELEGATE_BASE_URL` apuntando a la tailnet, `auto` pide turno a `https://<mismo host>:9393/` con la clave del backend que ya tiene | `LOCAL_DELEGATE_TURN_URL` (`auto`), `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` (opcional) |

Con la configuración de esta página (`LOCAL_DELEGATE_BASE_URL=https://pc.example-tailnet.ts.net:9292/v1`),
la Mac pide turno a `https://pc.example-tailnet.ts.net:9393/`. `tailscale serve` ya publica `9393`.
Si el puerto web de la PC no es el de la Mac, o hay un túnel `ssh -L` que hace parecer local al
backend, pon la URL explícita: `LOCAL_DELEGATE_TURN_URL=https://pc.example-tailnet.ts.net:9393`.

Para comprobarlo: `local_status` en la Mac dice «Turno remoto: activo en …», y
`local-delegate doctor` lo prueba de verdad en la línea «turno del daemon» (ver
[Integration & install](Integration-install.md)): en la Mac, que el daemon de la PC acepta su
credencial; en la PC, que su daemon tiene secreto y qué modelos no podría nombrar una operación
remota (el endpoint quita `:`, `/` y otros caracteres del nombre del modelo, y entonces responde
`no_turn`; la arreglas con un alias sin esos caracteres en la config de llama-swap, usado como
nombre en la Mac). La prueba de `doctor` es un `release` de un arrendamiento que no existe: no
ocupa turno ni toca nada.

### Seguridad

- **Credencial.** La Mac manda `Authorization: Bearer` con `LOCAL_DELEGATE_REMOTE_WEB_TOKEN` (o el
  Llavero, servicio `local-delegate-remote-web-token`) si existe y, si no, **la clave del backend**
  (`LOCAL_DELEGATE_API_KEY`), la misma que ya manda a `:9292`. El daemon de la PC acepta su token
  del puerto o esa clave, comparados en tiempo constante. Las **tres rutas** de `/api/turn/` son
  accesibles con la clave del backend aunque no tengas el token del puerto: quien la tiene ya puede
  usar la GPU directamente, así que el turno no le da nada nuevo. El resto del puerto sigue pidiendo
  su token. Solo `Bearer` (ni `Basic` ni la cookie del panel, ni peticiones con `Origin`: un
  navegador no puede usarlas). La credencial nunca se registra ni se devuelve.
- **`auto` nunca pregunta a un host público.** Solo descubre hosts privados, decididos por el texto
  y sin resolver DNS: IP de loopback, de red local, de la tailnet (`100.64.0.0/10`, `fd7a:…`) o
  link-local; un nombre `.ts.net`, `.local`, `.lan`, `.home.arpa` o `.internal`; o un nombre corto
  sin puntos. Con un backend público (`https://api.example.com/v1`) no se hace **ninguna** petición
  y la clave no sale; `local_status` dice «no disponible (public_host)».
- **Texto plano.** Con una URL explícita `http://` hacia un host que no es privado, el cliente avisa
  una vez en el log de errores y lo dice en `local_status` y en `doctor`: la credencial viajaría
  sin cifrar. Usa `https` o la dirección de la tailnet.
- **Nunca a sí mismo.** Una URL de loopback con el propio puerto web, o un daemon con el mismo
  `daemon_id` que el `daemon.json` local, es `self`: no se pide turno remoto.

### Degradación

El turno es una mejora, nunca un bloqueo:

- **Daemon de la PC inutilizable** (no responde, versión anterior o `TURN_SERVER=off` → 404,
  credencial rechazada → 401/403, respuesta ilegible): la operación **sigue sin turno, como
  antes**, y el evento lo dice en `remote_turn` (`unreachable`, `unsupported`, `unauthorized`,
  `needs_secret`, `bad_response`). El motivo va una vez por proceso al log de errores y se recuerda
  60 s (10 min con 404/405, o si no responde y nunca dio turno en ese proceso), para no pagar el plazo en cada
  operación.
- **Daemon lleno** (`429`, más de 16 arrendamientos o de 8 de una máquina): la Mac **espera** y
  reintenta, dentro de `LOCAL_DELEGATE_QUEUE_MAX_WAIT_S`; no se va sin turno.
- **Arrendamiento perdido** (`expired`: la Mac dejó de latir o la PC reinició el daemon): la llamada
  en curso termina, y antes del siguiente envío se vuelve a pedir turno al final de la cola.

Versiones mixtas: con una Mac anterior, la Mac va directa a `:9292` como siempre; con una PC
anterior, `acquire` da 404 y la Mac sigue sin turno (`remote_turn: "unsupported"`).

### Rollback

- **En la Mac:** `LOCAL_DELEGATE_TURN_URL=off` (en `~/.zshrc` y en el entorno de los clientes
  gráficos, como `LOCAL_DELEGATE_API_KEY` arriba). No pide turno nunca y vuelve al comportamiento
  anterior; `local_status` dice «Turno remoto: desactivado».
- **En la PC:** `LOCAL_DELEGATE_TURN_SERVER=off` en el entorno del daemon y reiniciarlo. El
  endpoint responde 404, como un daemon anterior, y las Macs siguen sin turno sin romper nada.

### Topología recomendada

Mientras `:9292` esté publicado en la tailnet, un cliente viejo o ajeno puede saltarse la cola. Por
orden:

1. **Ahora:** nada que cambiar; espera a que la Mac tenga la versión con el turno remoto.
2. **Con la Mac actualizada y `remote_turn: "granted"` en su log:** restringe `:9292` en la ACL de
   la tailnet a los dispositivos que usan local-delegate, para que nada ajeno lo use.
3. **Más adelante, si se mide tráfico que se salta la cola:** que el daemon publique el backend
   detrás de sí (una ruta que exija un arrendamiento vivo) y quitar `:9292` de `tailscale serve`
   (`tailscale serve --https=9292 off`). No está hecho: va en otra tarjeta.

## Verificación

Después de reiniciar el cliente:

1. ejecuta `local_status` y confirma backend disponible/modelos;
2. ejecuta `local_classify` con texto pequeño;
3. crea un archivo temporal en `/tmp` y llama `local_summarize(path=...)`;
4. abre el dashboard con `open "https://${PC_MAGICDNS}:9393"`.

Qué dice el panel cuando el cómputo es remoto (el panel del daemon de la Mac, si lo tienes):

- `local_status` dice `Backend: arriba` cuando todo va bien. Si no, dice la causa: `CAÍDO: no se
  resuelve el nombre …` (MagicDNS), `CAÍDO: … no contesta a la conexión` (ruta, cortafuegos o una
  VPN que se come el tráfico) o `SIN ACCESO: …` (la key no llega). La tabla completa está en
  [Troubleshooting](Troubleshooting.md).
- El badge del backend dice lo mismo: «conectado», «sin acceso» en ámbar o «caído · no contesta»
  en rojo. Un fallo suelto no lo cambia; hacen falta dos sondeos fallidos seguidos.
- La tarjeta Sistema lleva la fila **Backend** con el host como enlace al panel de esa máquina
  (mismo host, puerto web del daemon, en pestaña nueva; pide el token de aquella máquina). En macOS
  la fila **RAM / VRAM** dice «—». La explicación está en el botón ⓘ de la tarjeta.
- Con el backend remoto, una delegación que no puede conectar no pregunta «¿Lo arranco?» y se rinde
  a los 10 s, en vez de quedarse colgada lo que tarde macOS en agotar la conexión (~75 s).

El canary completo y el rollback están en la
[recipe técnica del backend remoto](../recipes/remote-backend.md).
El canary autenticado pasó 20/20,
concurrencia 2, dos arranques, `path` exclusivo de macOS y 401 sin key.
