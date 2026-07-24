# Recipe: MCP local en la Mac, modelos remotos en la PC

La topología recomendada mantiene `local-delegate` junto al cliente que posee los archivos y
solo mueve la inferencia OpenAI-compatible por la red:

```text
Codex/Claude en Mac -> local-delegate stdio en Mac -> red privada -> llama-swap en PC -> GPU
                            |
                            +-- abre /Users/... localmente
```

Esto preserva la ventaja de `local_summarize(path=...)`: la Mac abre el archivo y envía su
contenido al backend. Si el MCP entero corriera en la PC, un `path=/Users/...` se intentaría abrir
en Windows y fallaría. Tampoco hace falta un protocolo MCP-a-MCP adicional.

## 1. Exponer solamente el backend de la PC

Haz que llama-swap escuche en la IP de la interfaz privada, no en Internet público. El detalle de
la VPN o red queda fuera de esta recipe; usa aquí su dirección alcanzable:

```powershell
llama-swap --config D:\Projects\llms\llama-swap\config.yaml --listen <PC_PRIVATE_IP>:9292
```

Restringe el firewall de Windows al perfil/interfaz y a las IP privadas que realmente lo usan.
No abras `9292` al Internet público. Fuera de loopback, activa las `apiKeys` nativas de llama-swap
sin persistir el secreto en YAML:

```yaml
apiKeys:
  - "${env.LOCAL_DELEGATE_REMOTE_API_KEY}"
```

Define `LOCAL_DELEGATE_REMOTE_API_KEY` solamente en el entorno del proceso de llama-swap. En la Mac,
el mismo valor se entrega al MCP como `LOCAL_DELEGATE_API_KEY`; no lo escribas en documentación ni
logs. La sintaxis está documentada por llama-swap y mantiene el default sin auth solo cuando la
lista está ausente o vacía.

Canary desde la Mac, antes de registrar el MCP:

```bash
curl --fail --max-time 5 http://<PC_PRIVATE_IP>:9292/v1/models
```

Si el endpoint exige token:

```bash
curl --fail --max-time 5 \
  -H "Authorization: Bearer $LOCAL_DELEGATE_API_KEY" \
  http://<PC_PRIVATE_IP>:9292/v1/models
```

## 2. Mantener el MCP local en la Mac

### Elegir exactamente que revision se prueba

`uvx local-delegate-mcp` instala la ultima version publicada en PyPI. Por tanto, los cambios que
solo existen sin commit en la PC **no pueden aparecer en la Mac**. Para probar antes de publicar:

1. crea un commit de canary y subelo a una rama;
2. copia su SHA completo;
3. fija `uvx` a ese commit con `--from`.

```text
uvx --from git+https://github.com/ZahiriNatZuke/local-delegate.git@<COMMIT_SHA> local-delegate-mcp
```

Esto no publica una release y evita que un cambio posterior en la rama altere la prueba. Despues
de aprobar el canary se crea la version nueva, se publica en PyPI y se vuelve al comando estable
`uvx local-delegate-mcp` (o se fija `local-delegate-mcp==<VERSION>` durante el rollout).

En la entrada `local-delegate` del cliente MCP conserva `command: uvx` y añade este entorno:

```json
{
  "mcpServers": {
    "local-delegate": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/ZahiriNatZuke/local-delegate.git@<COMMIT_SHA>",
        "local-delegate-mcp"
      ],
      "env": {
        "LOCAL_DELEGATE_BASE_URL": "http://<PC_PRIVATE_IP>:9292/v1",
        "LOCAL_DELEGATE_AUTOSTART": "0"
      }
    }
  }
}
```

Añade `LOCAL_DELEGATE_API_KEY` mediante el almacén de secretos o entorno del cliente solo cuando
el endpoint lo exija. El auto-arranque debe quedar en `0`: la Mac no puede ni debe iniciar el
llama-swap de Windows.

En Claude Code, la forma menos ambigua de registrar el canary a nivel de usuario es guardar un
placeholder, no el secreto. Las comillas simples hacen que el shell no expanda la variable al
crear la entrada:

```bash
claude mcp remove local-delegate 2>/dev/null || true
claude mcp add-json --scope user local-delegate '{
  "type": "stdio",
  "command": "uvx",
  "args": [
    "--refresh",
    "--from",
    "git+https://github.com/ZahiriNatZuke/local-delegate.git@<COMMIT_SHA>",
    "local-delegate-mcp"
  ],
  "env": {
    "LOCAL_DELEGATE_BASE_URL": "http://<PC_PRIVATE_IP>:9292/v1",
    "LOCAL_DELEGATE_AUTOSTART": "0",
    "LOCAL_DELEGATE_API_KEY": "${LOCAL_DELEGATE_API_KEY}"
  }
}'
claude mcp get local-delegate
```

Antes de iniciar Claude Code desde esa terminal, carga el token desde Keychain al entorno. Este
ejemplo asume que ya existe un item `local-delegate-remote`; no muestra el valor:

```bash
export LOCAL_DELEGATE_API_KEY="$(security find-generic-password \
  -a "$USER" -s local-delegate-remote -w)"
claude
```

Si el backend no usa auth, elimina por completo la entrada `LOCAL_DELEGATE_API_KEY`. Si la Mac esta
administrada y no permite Keychain/variables o bloquea MCP personales, hay que coordinarlo con la
politica del equipo; no se debe pegar el token en el repo ni en un `.mcp.json` compartido.

### Canary automatizado desde la Mac

El script del repo levanta el MCP real por stdio, negocia MCP, lista tools, hace 20 inferencias,
procesa un archivo temporal exclusivo de la Mac, envia pares concurrentes y reinicia el proceso
para comprobar reconexion:

```bash
export LOCAL_DELEGATE_BASE_URL=http://<PC_PRIVATE_IP>:9292/v1
export LOCAL_DELEGATE_API_KEY='cargar-desde-tu-keychain'
python3 scripts/macos_mcp_canary.py \
  --package-source git+https://github.com/ZahiriNatZuke/local-delegate.git@<COMMIT_SHA> \
  --expect-auth
```

El script no imprime el token. Debe terminar con JSON `"status": "PASS"`, `20` llamadas, dos
arranques, concurrencia `2` y `mac_only_path: PASS`. Ejecutalo desde un checkout del mismo commit;
el codigo instalado y el script quedan asi amarrados a la misma revision.

Para automatizar tambien preflight, descarga y checkout, usa el wrapper con el SHA completo:

```bash
./scripts/run_macos_remote_canary.sh \
  <COMMIT_SHA> \
  https://<PC_MAGICDNS>:9292/v1
```

Si `LOCAL_DELEGATE_API_KEY` no esta cargada, el wrapper la pide sin mostrarla ni guardarla. Verifica
el endpoint autenticado, confirma que el commit existe en GitHub, crea un checkout temporal y corre
el canary de 20 llamadas desde esa revision exacta.

Después de reiniciar el cliente, ejecuta `local_status` y dos canaries:

1. `local_classify` con un texto pequeño, para validar red, modelo y respuesta.
2. `local_summarize(path=...)` con un archivo temporal de la Mac, para confirmar que `path` se
   resuelve del lado correcto.

## Alternativa: MCP remoto completo

`local-delegate serve --host <PC_PRIVATE_IP>` puede publicar `/mcp` desde la PC. Es útil para
operaciones que reciben `text`, pero no es el default recomendado: los paths son del filesystem de
Windows, centraliza logs en la PC y expone otra superficie HTTP que hay que autenticar. Úsalo solo
si los archivos también viven en la PC o el cliente envía texto explícitamente.

## Criterio de aceptación

- `/v1/models` responde desde la Mac sin exponer el puerto públicamente.
- `local_status` no imprime ni registra el token.
- clasificación pequeña y resumen por `path` completan correctamente.
- al cortar la red, el fallo es rápido y claro; no intenta autoarrancar nada en la Mac.
- al volver a `http://127.0.0.1:9292/v1`, el flujo local sigue funcionando sin cambiar código.
