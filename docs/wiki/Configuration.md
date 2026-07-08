# Configuration

Todo se configura por variables de entorno (en el bloque `env` de tu config MCP, o en el shell).
Nada está hardcodeado.

## Endpoint

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` | Endpoint OpenAI-compatible |
| `LOCAL_DELEGATE_API_KEY` | *(vacío)* | Bearer token, si el endpoint lo exige |
| `LOCAL_DELEGATE_TIMEOUT` | `180` | Timeout HTTP (segundos) |

## Catálogo de modelos (roles)

Los defaults apuntan a un setup de referencia con llama-swap; cámbialos por los ids de tu backend.

| Variable | Default | Rol |
|---|---|---|
| `LOCAL_DELEGATE_MODEL_MECHANICAL` | `gemma3-4b` | clasificar, extraer, resumen corto |
| `LOCAL_DELEGATE_MODEL_LONG` | `llama31-8b` | documentos largos |
| `LOCAL_DELEGATE_MODEL_CODE` | `qwen25-coder-14b` | código |
| `LOCAL_DELEGATE_MODEL_FAST` | `qwen35-2b` | ultrarrápido / trivial |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | umbral mecánico↔largo |
| `LOCAL_DELEGATE_MAX_CHARS_MECHANICAL` / `_LONG` / `_CODE` / `_FAST` | `20000` / `48000` / `20000` / `12000` | tope de chars de entrada por modelo |

> `local_delegate` (tool genérica) valida su parámetro `model` contra el conjunto de estos 4 ids.
> Si dos roles apuntan al mismo id, el catálogo se deduplica sin problema.

## Web de métricas

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_WEB` | `1` | `0` desactiva la web embebida |
| `LOCAL_DELEGATE_WEB_HOST` | `127.0.0.1` | Host de la web |
| `LOCAL_DELEGATE_WEB_PORT` | `9393` | Puerto de la web |

## Log de uso

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_LOG` | *(dir de datos de usuario)* | Ruta del `usage.jsonl`. Por defecto `platformdirs.user_data_dir("local-delegate")` (p. ej. `%LOCALAPPDATA%\local-delegate\usage.jsonl` en Windows) |

## Auto-arranque de llama-swap (opt-in)

Solo se usa si `LOCAL_DELEGATE_AUTOSTART=1`. Específico de llama-swap.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_AUTOSTART` | `0` | `1` intenta arrancar llama-swap si el endpoint no responde |
| `LLAMASWAP_EXE` | *(busca `llama-swap` en PATH)* | Ruta al ejecutable |
| `LLAMASWAP_CONFIG` | *(vacío)* | Ruta al `config.yaml` de llama-swap |
| `LLAMASWAP_LISTEN` | `127.0.0.1:9292` | host:puerto de llama-swap |
