# Troubleshooting

## `[local-delegate error] no se pudo conectar al endpoint`

El backend OpenAI-compatible no responde en `LOCAL_DELEGATE_BASE_URL`.

- Verifica que tu backend corre: `curl http://127.0.0.1:9292/v1/models`.
- Si usas llama-swap y quieres que el MCP lo arranque solo, activa el opt-in
  (`LOCAL_DELEGATE_AUTOSTART=1` + `LLAMASWAP_CONFIG`/`LLAMASWAP_EXE`). Ver
  [recipe de llama-swap](../recipes/llama-swap-blackwell.md).
- Otros backends (Ollama, LM Studio, vLLM) los arrancas tú; el auto-arranque es solo llama-swap.

Si el backend está en otra máquina:

- `Could not resolve host`: MagicDNS no está resolviendo; prueba primero `tailscale status` y
  `tailscale ping <PC>` desde la Mac.
- `Operation timed out`: DNS resolvió, pero falta ruta/grant o Tailscale Serve no está activo.
- `401`: la red funciona; carga la key desde Keychain y confirma el header Bearer.
- No cambies a MCP remoto completo para “arreglar” `path`: el MCP debe seguir local en la Mac.

Guía completa: [Backend remoto Mac → PC](Remote-backend.md).

## `[local-delegate error] <modelo> respondió 404` (o "model not found")

Los ids de modelo configurados no existen en tu backend. Ajusta
`LOCAL_DELEGATE_MODEL_MECHANICAL/_LONG/_CODE/_FAST` a los ids reales (p. ej. con Ollama,
`llama3.1`, `qwen2.5-coder:14b`…). Ver [Configuration](Configuration.md).

## `uvx` no encuentra el comando / Claude no arranca el MCP

- Usa la ruta absoluta a `uvx` en `command` (Claude Desktop puede no heredar tu PATH),
  p. ej. `C:\Users\<tu>\.local\bin\uvx.exe`.
- El comando del paquete es `local-delegate-mcp` (o el alias `local-delegate`).

## La web no aparece en `http://127.0.0.1:9393`

- En modo daemon, verifica `GET http://127.0.0.1:9393/api/daemon` y arranca
  `local-delegate serve` si no responde.
- ¿`LOCAL_DELEGATE_WEB=0`? Quítalo.
- Si hay **otra instancia** de Claude (Code + Desktop) ya sirviendo el puerto, la segunda no monta
  una web embebida nueva. Migra los clientes al [daemon compartido](Daemon.md) para eliminar esa
  dependencia del ciclo de vida de `stdio`.

## El modelo tarda mucho en la primera llamada

Es el *cold-load* en VRAM (llama-swap carga el modelo al vuelo). Las siguientes van calientes.
Ajusta el `ttl` de llama-swap para el equilibrio VRAM/latencia — ver
[recipe · Descarga de VRAM](../recipes/llama-swap-blackwell.md#descarga-de-vram-ttl).

## El dashboard está vacío

No hay ningún `usage-YYYYMM.jsonl` todavía (se crea en la primera delegación tras arrancar
el MCP), o `LOCAL_DELEGATE_LOG_DIR`/`LOCAL_DELEGATE_LOG` apunta a otra ruta que la que lee
la web. El pie del dashboard muestra cuántos archivos leyó (`files_read`) — si es 0, es
justo esto.
