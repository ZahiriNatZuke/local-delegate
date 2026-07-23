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
| `LOCAL_DELEGATE_MODEL_VISION` | `qwen3-vl-8b` | visión (imagen→texto, `local_describe_image`) |
| `LOCAL_DELEGATE_LONG_INPUT_CHARS` | `6000` | umbral mecánico↔largo |
| `LOCAL_DELEGATE_MAX_CHARS_MECHANICAL` / `_LONG` / `_CODE` / `_FAST` | `20000` / `48000` / `20000` / `12000` | tope de chars de entrada por modelo |
| `LOCAL_DELEGATE_MAX_IMAGE_MB` | `8` | tope de tamaño de imagen para `local_describe_image` |

> `local_delegate` (tool genérica) valida su parámetro `model` contra el conjunto de estos 4 ids
> de texto. `MODEL_VISION` queda fuera a propósito: ese rol no arma payload texto→texto.
> Si dos roles apuntan al mismo id, el catálogo se deduplica sin problema.

## Daemon y web de métricas

`local-delegate serve` usa el host/puerto web para servir MCP en `/mcp` y dashboard en `/`.
En modo `stdio`, las mismas variables controlan únicamente la web embebida heredada.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_WEB` | `1` | `0` desactiva la web embebida del modo `stdio` |
| `LOCAL_DELEGATE_WEB_HOST` | `127.0.0.1` | Host de web/daemon |
| `LOCAL_DELEGATE_WEB_PORT` | `9393` | Puerto único de web/daemon |

## Log de uso

Por defecto el log rota por mes (`usage-YYYYMM.jsonl`, mes UTC) dentro de `LOG_DIR`. Si
fijas `LOCAL_DELEGATE_LOG`, ese archivo se usa tal cual y la rotación se desactiva
(compatibilidad con instalaciones que ya apuntaban a una ruta fija).

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_LOG_DIR` | *(dir de datos de usuario)* | Directorio donde se escriben los `usage-YYYYMM.jsonl` rotados. Por defecto `platformdirs.user_data_dir("local-delegate")` (p. ej. `%LOCALAPPDATA%\local-delegate` en Windows) |
| `LOCAL_DELEGATE_LOG` | *(vacío = rotación activa)* | Si se fija, ruta de un `usage.jsonl` explícito sin rotar. El dashboard igual lo lee como fuente adicional aunque uses `LOG_DIR` para el resto |
| `LOCAL_DELEGATE_FEEDBACK` | `1` | `0` apaga la línea "leído server-side: N chars ≈ M tokens" que se anexa al resultado cuando `source=path` |

## `local_extract` — JSON con schema

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_JSON_SCHEMA` | `auto` | `auto` pide `response_format` con schema y cae a modo libre si el backend responde 400; `on` lo exige (propaga el error); `off` nunca lo pide |

## Seguridad — raíces permitidas

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_ALLOWED_DIRS` | *(vacío = sin restricción)* | Lista de directorios raíz separados por `;`. Cualquier `path` fuera de todos ellos se rechaza con un error que lista las raíces permitidas |

## Auto-arranque de llama-swap (opt-in)

Solo se usa si `LOCAL_DELEGATE_AUTOSTART=1`. Específico de llama-swap.

| Variable | Default | Descripción |
|---|---|---|
| `LOCAL_DELEGATE_AUTOSTART` | `0` | `1` intenta arrancar llama-swap si el endpoint no responde |
| `LLAMASWAP_EXE` | *(busca `llama-swap` en PATH)* | Ruta al ejecutable |
| `LLAMASWAP_CONFIG` | *(vacío)* | Ruta al `config.yaml` de llama-swap |
| `LLAMASWAP_LISTEN` | `127.0.0.1:9292` | host:puerto de llama-swap |
| `LLAMASWAP_WATCH_CONFIG` | `0` | `1` añade `-watch-config` cuando hay `LLAMASWAP_CONFIG` |
