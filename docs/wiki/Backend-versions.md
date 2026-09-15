# Versiones del backend y workspace de referencia

`local-delegate` es un **cliente genérico** de cualquier endpoint OpenAI-compatible: **no instala
ni fija versiones** de `llama-server`/`llama-swap`, y funciona con Ollama, LM Studio o vLLM sin
nada de esto. Esta página es solo una **referencia probada**: las versiones y la disposición de
carpetas con las que el autor verifica cada release. Ni requisito ni obligación — una sugerencia.

## Versiones probadas

| Componente | Versión probada | Verificado | Notas |
|---|---|---|---|
| `local-delegate` | 0.14.0 | 2026-07-30 | esta release |
| `llama-server` (llama.cpp) | **b10909** | 2026-09-15 | RTX 5060 (Blackwell/sm_120), runtime **CUDA 13.3**; `--version` pasa a semver (`0.4.0-dev (build 10909, ...)`) y trae `--fit on` por defecto: fija `--fit off -ngl 99` si quieres un OOM claro en vez de capas recortadas en silencio |
| `llama-swap` | **v255** | 2026-09-15 | acepta la misma config que v238 (`groups`, `apiKeys` con `${env...}`); sin la variable de la clave **no arranca**, en vez de quedar abierto |

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
  │   └─ config.yaml           (modelos + groups; ver recipes)
  ├─ llama-swap-v255\
  │   └─ llama-swap.exe        (v255)
  ├─ llamacpp-b10909\
  │   ├─ llama-server.exe      (b10909)
  │   └─ *.dll                 (ggml-*, cudart64_13, cublas64_13, cublasLt64_13)
  └─ models\                   (una subcarpeta por modelo)
      ├─ gemma3-4b\*.gguf
      ├─ gemma4-26b-a4b\*.gguf
      ├─ qwen36-35b-a3b\*.gguf
      ├─ gemma4-12b\*.gguf     (+ mmproj-*.gguf para visión)
      └─ Qwen3.5-2B\*.gguf
```

Variables de entorno que enlazan las piezas (en el config del host MCP — Claude Desktop/Code):

| Variable | Valor de referencia |
|---|---|
| `LOCAL_DELEGATE_BASE_URL` | `http://127.0.0.1:9292/v1` |
| `LLAMASWAP_EXE` | `D:\Projects\llms\llama-swap-v255\llama-swap.exe` |
| `LLAMASWAP_CONFIG` | `D:\Projects\llms\llama-swap\config.yaml` |

El detalle de GPU (build CUDA para Blackwell, `-ngl`, flash-attn) está en el
[recipe de llama-swap Blackwell](../recipes/llama-swap-blackwell.md); los `groups`
(residente + swap) en el [recipe de groups](../recipes/llama-swap-groups.md).

## Chequear tu instalación: `local-delegate doctor`

Detecta las versiones instaladas y avisa si conviene actualizar respecto a las probadas (además
del andamiaje y el daemon, que se documentan en
[Instalación de la integración](./Integration-install.md#comprobar-la-instalación-local-delegate-doctor)):

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

## Medir un canary: `local-delegate benchmark`

Lo que `doctor` no puede decirte es si una versión nueva del backend **rinde** igual. Para eso está
`benchmark`, que corre un corpus de **tareas reales** contra un backend candidato y escribe los
resultados en JSONL, con las condiciones anotadas (cuantización, contexto, `--n-cpu-moe`, versiones
de llama-server/llama-swap), para que dos corridas sean comparables:

```bash
local-delegate benchmark --model <id-del-canary> --label gemma4-e4b-c16k \
  --cases benchmarks/catalogo-2026-09/cases.json --role mechanical --runs 5 --save-responses
```

Es la herramienta del paso «canary aislado» de arriba: mide antes de promover, en vez de decidir
por impresión.

El corpus (`schema_version: 2`) sale de delegaciones reales del log de uso: cada caso manda **el
prompt de producción de su tool** sobre una fuente congelada, y el runner **falla** si el hash de la
fuente no cuadra. El corpus sintético de julio (`benchmarks/moe/`) ya no se carga. `--role` y
`--case` eligen qué corre; `--input-control` sustituye la imagen de los casos de visión por la de
control. `--reasoning-effort off` apaga el razonamiento (`enable_thinking: false`), y un valor
propio del caso manda sobre el del modelo. `--context-size` y `--load-mode` quedan en el registro
y hay que pasarlos siempre: el análisis solo compara dos modelos medidos con los mismos.

Cada registro trae un `outcome`, y no todo lo que no es `ok` es mala calidad:

| `outcome` | Qué significa | ¿Puntúa? |
| --- | --- | --- |
| `ok` | respuesta completa | sí |
| `truncado` | se cortó por `max_tokens`; se repite **una vez** con el doble, y si vuelve a cortarse puntúa **0** (`zero_by: truncado_repetido`) | la primera vez no; la repetida, 0 |
| `rechazo_por_contexto` | el prompt no cabe en el contexto del modelo (`exceed_context_size_error`) | no |
| `configuracion` | gastó el presupuesto pensando y no contestó | no |
| `error` | cualquier otro fallo; el exit code pasa a `1` | no |

La puntuación normaliza antes de comparar (una tilde no resta cobertura), pone la calidad a 0 si
aparece un término prohibido y guarda en `zero_by` **qué componente** la hundió. Aparte va
`descartada`: la sonda anuló la corrida, y el runner **la repite** con los mismos `max_tokens`
hasta dos veces. Cada intento lleva `retry_reason` (`anulada` o `truncado`) y el análisis juzga la
corrida por el último. `thermal_state` es `cold` solo en la primera petición tras cambiar el proceso
de `llama-server`, y `null` sin sonda.

Los casos con `execution_checks` (hoy `boilerplate-156`) **ejecutan el código generado**: pasa por
el mismo quitado de vallas que `local_boilerplate` antes de escribir a disco, corre en otro proceso
con `python -I`, en una carpeta temporal, con entorno vacío, sin stdin y con 10 s de tope, y la
calidad es el mínimo entre la cobertura y la proporción de comprobaciones que pasan
(`execution_ratio`, y cuáles en `execution_passed`). No es un sandbox del sistema: es código de un
modelo corriendo en tu máquina, y correr el caso es aceptarlo.

Cada petición usa **la temperatura de producción** de su tool y la semilla `--seed + corrida - 1`
(la misma en los reintentos), y por defecto son **5 corridas**: con temperatura 0 las corridas
salían idénticas y no había ruido que medir. Además del puntuador, cada registro guarda si la
respuesta respeta el **formato** que pide la tool (`format_ok`: límite de palabras y prosa), como
dato: no entra en la calidad. En `lint-9k` los conteos se comprueban contra la salida de ruff
(`counts_ratio`).

**No todos los casos los juzga la fórmula.** Los de texto abierto —resúmenes, explicaciones, el
mensaje de commit y el resumen de lint— llevan `automatic_scoring: false`: una comparación por
pares a ciegas mostró que la cobertura de términos coincidía con el juicio humano en 6 de 13 pares.
Esos casos se deciden con `scripts/hoja_pares.py` (empareja la corrida *i* de dos modelos, sortea el
lado y guarda la clave aparte) y `scripts/analizar_benchmark.py decidir --pares`, que aplica una
prueba de signos. Las métricas objetivas —ejecución, JSON y campos, cifras de una imagen— siguen
decidiendo donde las hay.

En Windows, `--probe-process llama-server.exe` añade a cada corrida la memoria **del proceso**, no
la del sistema: RAM privada y working set (por `GetProcessMemoryInfo`), y VRAM dedicada y
compartida del adaptador indicado con `--gpu-luid` (por `typeperf`; sin el flag se empareja con
`nvidia-smi` y, si no es inequívoco, pide el flag). El proceso se busca **por nombre** en cada
lectura, porque llama-swap lo relanza al cambiar de modelo. Cada registro lleva un bloque
`resources` con los picos y un campo `annul`: una corrida sin muestras, con dos `llama-server`
vivos o con cambio de proceso a mitad **se repite** (hasta dos veces), no se publica vacía. Sin el flag,
el bloque va igual pero vacío. Si `typeperf` arranca antes de que `llama-server` cree su contexto de
GPU, su cabecera no trae el proceso: la sonda lo relanza con el mismo PID, como mucho cada 3 s. Para `llama-bench`, que no pasa por el runner, el mismo muestreo está
en `scripts/sonda_recursos.py`.

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
  --resident gemma3-4b --swap gemma4-26b-a4b,qwen36-35b-a3b \
  --store-path D:\Projects\llms\llama-swap\metrics.db
```

Sin `store.path`, llama-swap guarda las métricas solo en memoria (se pierden al reiniciar) y el
panel las muestra igual mientras el proceso siga vivo.
