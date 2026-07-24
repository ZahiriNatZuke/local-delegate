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

Comprueba desde la Mac, sustituyendo una vez `PC_MAGICDNS` por el nombre de la PC:

```bash
export LOCAL_DELEGATE_BASE_URL="https://PC_MAGICDNS:9292/v1"
export LOCAL_DELEGATE_API_KEY="$(security find-generic-password \
  -a "$USER" -s local-delegate-remote -w)"

curl --fail --max-time 5 \
  -H "Authorization: Bearer $LOCAL_DELEGATE_API_KEY" \
  "$LOCAL_DELEGATE_BASE_URL/models"
```

Debe devolver JSON de modelos. `401` significa key ausente/incorrecta; timeout significa ruta,
grant o Serve; error DNS significa MagicDNS.

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

Para Codex, usa el mismo `command`, `args` y tres variables en la configuración de MCP de usuario.
El inventario debe conservar el mismo ámbito funcional en ambos clientes.

## Verificación

Después de reiniciar el cliente:

1. ejecuta `local_status` y confirma backend disponible/modelos;
2. ejecuta `local_classify` con texto pequeño;
3. crea un archivo temporal en `/tmp` y llama `local_summarize(path=...)`;
4. confirma que el dashboard abre en `https://PC_MAGICDNS:9393`.

El canary completo y el rollback están en la
[recipe técnica](../recipes/remote-backend.md). El canary autenticado de 0.10.0 pasó 20/20,
concurrencia 2, dos arranques, `path` exclusivo de macOS y 401 sin key.
