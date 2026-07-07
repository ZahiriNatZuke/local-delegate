# Recipe: llama-swap en una RTX 5060 (Blackwell)

Setup de referencia del autor: **llama-swap** sirviendo 4 modelos GGUF en
`127.0.0.1:9292`, sobre una **RTX 5060 (arquitectura Blackwell, sm_120)**. Es el backend
concreto detrás de los defaults del paquete; cámbialo por el tuyo con las env vars.

## Por qué llama-swap

`local-delegate` enruta a 4 *roles* de modelo (mecánico, largo, código, rápido). Cargar los
4 a la vez no cabe en 8 GB de VRAM. **llama-swap** actúa de proxy OpenAI-compatible y hace
*hot-swap*: carga el modelo pedido en VRAM al vuelo y descarga el anterior. Así un solo
endpoint (`:9292/v1`) expone los 4 modelos sin tenerlos todos residentes.

## Modelos (roles → ids)

| Rol (env) | id en llama-swap | GGUF sugerido |
|---|---|---|
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | Gemma 3 4B Q4_K_M |
| `LOCAL_DELEGATE_MODEL_LONG` | `llama31-8b` | Llama 3.1 8B Q4_K_M (ctx amplio) |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen25-coder-14b` | Qwen2.5-Coder 14B Q4_K_M |
| `LOCAL_DELEGATE_MODEL_FAST` | `qwen35-2b` | Qwen ~2B Q4_K_M |

Son los defaults del paquete: con estos ids no necesitas configurar nada.

## `config.yaml` de llama-swap (esquema)

```yaml
# llama-swap/config.yaml
models:
  gemma3-4b:
    cmd: >
      llama-server --model D:\models\gemma-3-4b-it-Q4_K_M.gguf
      --port ${PORT} --ctx-size 8192 --n-gpu-layers 999 --flash-attn
  llama31-8b:
    cmd: >
      llama-server --model D:\models\Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
      --port ${PORT} --ctx-size 16384 --n-gpu-layers 999 --flash-attn
  qwen25-coder-14b:
    cmd: >
      llama-server --model D:\models\Qwen2.5-Coder-14B-Instruct-Q4_K_M.gguf
      --port ${PORT} --ctx-size 8192 --n-gpu-layers 999 --flash-attn
  qwen35-2b:
    cmd: >
      llama-server --model D:\models\Qwen2.5-2B-Instruct-Q4_K_M.gguf
      --port ${PORT} --ctx-size 8192 --n-gpu-layers 999 --flash-attn
```

llama-swap sustituye `${PORT}` por un puerto interno y hace de proxy en `--listen 127.0.0.1:9292`.

## Notas Blackwell (sm_120)

- Usa un build de **llama.cpp / llama-server con CUDA** que soporte Blackwell (sm_120). Si tu
  binario es previo a Blackwell, recompila con el toolkit CUDA correspondiente o usa un release
  reciente que ya lo incluya.
- `--flash-attn` acelera y reduce memoria; verifícalo con tu build.
- `--n-gpu-layers 999` sube todas las capas a la GPU (con 8 GB, los Q4_K_M de 4–8B caben; el
  14B va justo — por eso el hot-swap de llama-swap es clave).
- La **primera** llamada a cada modelo paga la carga en VRAM (latencia alta puntual); las
  siguientes van calientes. El dashboard lo refleja en "Latencia media".

## Arranque

**Manual:**
```bash
llama-swap --config D:\Projects\llms\llama-swap\config.yaml --listen 127.0.0.1:9292
```

**Auto-arranque desde el MCP (opt-in):** añade este `env` al bloque `local-delegate` de tu
config de Claude para que el MCP levante llama-swap si no está corriendo:

```json
"env": {
  "LOCAL_DELEGATE_AUTOSTART": "1",
  "LLAMASWAP_CONFIG": "D:\\Projects\\llms\\llama-swap\\config.yaml",
  "LLAMASWAP_EXE": "C:\\Users\\<tu-usuario>\\AppData\\Local\\Microsoft\\WinGet\\Links\\llama-swap.exe"
}
```

En Windows, `local-delegate` lanza llama-swap con `CREATE_NO_WINDOW` (consola oculta, sin
ventanas huérfanas de `nvidia-smi`) y el proceso **sobrevive** al MCP.
