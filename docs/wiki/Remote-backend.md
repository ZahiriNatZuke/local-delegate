# Backend remoto Mac → PC

La configuración recomendada ejecuta el MCP en la Mac y solo manda inferencia al llama-swap de la
PC. Así `local_summarize(path="/Users/...")` abre el archivo en la Mac y conserva el ahorro de
contexto; un MCP ejecutado entero en Windows no puede abrir ese path.

```text
Codex/Claude (Mac) -> local-delegate 0.10.0 (Mac) -> HTTPS privado -> llama-swap (PC) -> GPU
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

## Claude Code en la Mac

La entrada se fija a 0.10.0 durante el rollout. La key no se pega en el JSON: Claude expande la
variable que cargaste desde Keychain al iniciar la sesión.

```bash
claude mcp remove local-delegate 2>/dev/null || true
claude mcp add-json --scope user local-delegate "$(cat <<JSON
{
  \"type\": \"stdio\",
  \"command\": \"uvx\",
  \"args\": [
    \"--from\",
    \"local-delegate-mcp==0.10.0\",
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
args = ["--from", "local-delegate-mcp==0.10.0", "local-delegate-mcp"]
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
vez este LaunchAgent: obtiene la key desde Keychain al iniciar sesión y la deja en el entorno de
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

## Verificación

Después de reiniciar el cliente:

1. ejecuta `local_status` y confirma backend disponible/modelos;
2. ejecuta `local_classify` con texto pequeño;
3. crea un archivo temporal en `/tmp` y llama `local_summarize(path=...)`;
4. abre el dashboard con `open "https://${PC_MAGICDNS}:9393"`.

El canary completo y el rollback están en la
[recipe técnica de v0.10.0](https://github.com/ZahiriNatZuke/local-delegate/blob/v0.10.0/docs/recipes/remote-backend.md).
El canary autenticado pasó 20/20,
concurrencia 2, dos arranques, `path` exclusivo de macOS y 401 sin key.
