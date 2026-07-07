# Recipe: Ollama

[Ollama](https://ollama.com) expone una API OpenAI-compatible en `http://127.0.0.1:11434/v1`,
así que `local-delegate` funciona con él sin auto-arranque (Ollama ya corre como servicio).

## 1. Descarga modelos

```bash
ollama pull llama3.1
ollama pull qwen2.5-coder:14b
ollama pull gemma3:4b
```

## 2. Configura el MCP

Apunta el endpoint a Ollama y mapea los roles a los nombres de modelo de Ollama:

```json
{
  "mcpServers": {
    "local-delegate": {
      "command": "uvx",
      "args": ["local-delegate-mcp"],
      "env": {
        "LOCAL_DELEGATE_BASE_URL": "http://127.0.0.1:11434/v1",
        "LOCAL_DELEGATE_MODEL_MECHANICAL": "gemma3:4b",
        "LOCAL_DELEGATE_MODEL_LONG": "llama3.1",
        "LOCAL_DELEGATE_MODEL_CODE": "qwen2.5-coder:14b",
        "LOCAL_DELEGATE_MODEL_FAST": "gemma3:4b"
      }
    }
  }
}
```

## Notas

- `LOCAL_DELEGATE_AUTOSTART` no aplica: Ollama se gestiona solo (`ollama serve` o el servicio
  de escritorio). El auto-arranque del paquete es específico de llama-swap.
- Ollama hace su propio swap de modelos en VRAM; no necesitas un proxy adicional.
- Si un rol y otro apuntan al mismo modelo, no pasa nada: el catálogo se deduplica.
- Ajusta el contexto de cada modelo con un `Modelfile` de Ollama si procesas documentos largos.
