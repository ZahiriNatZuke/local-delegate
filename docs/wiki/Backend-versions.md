# Versiones del backend y workspace de referencia

`local-delegate` es un **cliente genérico** de cualquier endpoint OpenAI-compatible: **no instala
ni fija versiones** de `llama-server`/`llama-swap`, y funciona con Ollama, LM Studio o vLLM sin
nada de esto. Esta página es solo una **referencia probada**: las versiones y la disposición de
carpetas con las que el autor verifica cada release. Ni requisito ni obligación — una sugerencia.

## Versiones probadas

| Componente | Versión probada | Verificado | Notas |
|---|---|---|---|
| `local-delegate` | 0.10.0 | 2026-07-23 | esta release |
| `llama-server` (llama.cpp) | **b9925** | 2026-07-11 | RTX 5060 (Blackwell/sm_120), runtime **CUDA 13.3** |
| `llama-swap` | **v238** | 2026-07-11 | trae `status` en `/v1/models` (#901) y métricas SQLite (#898) |

> Fuente de verdad: `RECOMMENDED_VERSIONS` en
> [`src/local_delegate/doctor.py`](../../src/local_delegate/doctor.py). El comando
> `local-delegate doctor` compara tu instalación contra estos valores (ver abajo).

Ambos proyectos publican en *rolling release* (llama.cpp etiqueta casi cada merge; llama-swap
numera correlativo). No hay canal "estable" vs "nightly": para actualizar, toma un build con unos
días de rodaje en vez del filo absoluto, y verifica una inferencia real antes de confiar en él.

## Workspace de referencia

Todo vive autocontenido bajo un único raíz (aquí `D:\Projects\llms\`):

```
D:\Projects\llms\              ← raíz único, autocontenido
  ├─ llama-swap\
  │   ├─ llama-swap.exe        (v238)
  │   └─ config.yaml           (modelos + groups; ver recipes)
  ├─ llamacpp\
  │   ├─ llama-server.exe      (b9925)
  │   └─ *.dll                 (ggml-*, cudart64_13, cublas64_13, cublasLt64_13)
  └─ models\                   (una subcarpeta por modelo)
      ├─ gemma3-4b\*.gguf
      ├─ llama31-8b\*.gguf
      ├─ qwen25-coder-14b\*.gguf
      ├─ qwen3-vl-8b\*.gguf    (+ mmproj-*.gguf para visión)
      └─ Qwen3.5-2B\*.gguf
```

Variables de entorno que enlazan las piezas (en el config del host MCP — Claude Desktop/Code):

| Variable | Valor de referencia |
|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` |
| `LLAMASWAP_EXE` | `D:\Projects\llms\llama-swap\llama-swap.exe` |
| `LLAMASWAP_CONFIG` | `D:\Projects\llms\llama-swap\config.yaml` |

El detalle de GPU (build CUDA para Blackwell, `-ngl`, flash-attn) está en el
[recipe de llama-swap Blackwell](../recipes/llama-swap-blackwell.md); los `groups`
(residente + swap) en el [recipe de groups](../recipes/llama-swap-groups.md).

## Chequear tu instalación: `local-delegate doctor`

Detecta las versiones instaladas y avisa si conviene actualizar respecto a las probadas:

```bash
local-delegate doctor --config D:\Projects\llms\llama-swap\config.yaml
local-delegate doctor --online   # además compara con la última release en GitHub
```

Con `--online`, una release más nueva pasa por una compuerta explícita y se listan hasta tres
issues abiertos recientes cuyos títulos contienen señales como crash, deadlock, regression, CUDA,
Windows, TTL u OOM:

- menos de **7 días** publicada: `HOLD`; no se prueba ni se promueve todavía;
- 7 días o más: puede entrar a un canary aislado, pero no sustituye la versión probada;
- solo después del canary, las pruebas del paquete y una revisión de issues de regresión se
  actualiza `RECOMMENDED_VERSIONS` y esta página.

`latest` significa solamente «lo último publicado». La fuente de verdad operativa sigue siendo la
versión probada de la tabla superior.

- Localiza `llama-swap` vía `LLAMASWAP_EXE` (o el PATH) y `llama-server` desde el `cmd` del
  `config.yaml`. Funciona sin el extra `[llamaswap]`.
- Exit code `0` si todo está al día respecto a lo probado, `1` si hay actualizaciones sugeridas.

## Métricas persistentes del backend (#898)

llama-swap ≥ v236 puede persistir sus métricas de actividad (tokens/s, percentiles) en SQLite y
exponerlas en `GET /api/metrics/stats`. El dashboard de `local-delegate` las muestra en el panel
**"Rendimiento del backend"** (vía `/api/backend/stats`). Para que **sobrevivan a reinicios**,
añade `store.path` al `config.yaml` de llama-swap — `init-llamaswap` puede escribirlo:

```bash
local-delegate init-llamaswap --config config.yaml --vram-gb 16 \
  --resident gemma3-4b --swap llama31-8b,qwen25-coder-14b \
  --store-path D:\Projects\llms\llama-swap\metrics.db
```

Sin `store.path`, llama-swap guarda las métricas solo en memoria (se pierden al reiniciar) y el
panel las muestra igual mientras el proceso siga vivo.
