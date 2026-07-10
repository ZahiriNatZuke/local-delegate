# Recipe: groups de llama-swap (residente + swap, con guardrail de VRAM)

Por defecto, llama-swap corre **un modelo a la vez**: cada request hot-swapea el modelo activo.
Eso funciona bien pero paga un "cold-load" (unos segundos) cada vez que Claude delega a un
modelo distinto del que ya estaba cargado. Si delegás seguido a roles distintos (mecánico +
código, por ejemplo), tiene sentido mantener **un modelo residente siempre cargado** mientras
el resto sigue turnándose. Eso es exactamente lo que resuelven los **groups** de llama-swap.

> **El paquete nunca toca tu `config.yaml` por su cuenta.** Estos dos comandos (`check-llamaswap`,
> `init-llamaswap`) son **opt-in**: solo corren si vos los invocás explícitamente. Un `groups:`
> mal armado puede provocar OOM o thrashing de VRAM — por eso el default es no tocar nada, y por
> eso `init-llamaswap` corre el guardrail de VRAM (`check-llamaswap`) **antes** de escribir y
> nunca sobreescribe sin `--force` (dejando `.bak`).

## Instalación

Estos comandos requieren el extra opcional `[llamaswap]` (dependencia `pyyaml`):

```bash
pip install "local-delegate-mcp[llamaswap]"
# o, si instalaste con uv/uvx:
uv tool install "local-delegate-mcp[llamaswap]"
```

Sin el extra, el resto del paquete (el MCP, las 11 tools) funciona exactamente igual — estos
comandos solo fallan con un mensaje claro si intentás usarlos sin `pyyaml` instalado.

## Semántica de `groups` (verificada contra el código real de llama-swap)

llama-swap tiene hoy DOS mecanismos para correr más de un modelo a la vez: `groups` (el
histórico, "legacy" mas no deprecado — sigue siendo el router **default**) y `matrix` (un DSL
más nuevo basado en un solver, pensado para combinaciones complejas de modelos concurrentes).
Esta recipe usa `groups`, que es el que mapea directo al caso de uso "un residente + un pool
que se turna":

```yaml
groups:
  resident:
    persistent: true   # otros grupos no pueden descargar los modelos de este
    swap: false         # todos los miembros de este grupo corren juntos (acá: 1 solo)
    exclusive: false     # cargar este grupo NO descarga a los demás
    members: [gemma3-4b]
  swap:
    swap: true           # solo 1 modelo de este grupo corre a la vez (hot-swap normal)
    exclusive: false      # cargar un modelo de este grupo NO descarga 'resident'
    members: [llama31-8b, qwen25-coder-14b]
```

Puntos que sorprenden si venís de la doc vieja o de memoria:

- **`ttl` no es una clave de `groups`.** Es una clave **por modelo** (`models.<id>.ttl`) o
  global (`globalTTL`). `init-llamaswap` fija `ttl:` en cada modelo referenciado por
  `--resident`/`--swap`, no en el grupo.
- `exclusive` controla si cargar un modelo de este grupo **descarga todos los demás grupos**.
  Para el patrón residente+swap lo querés en `false` en ambos grupos (si no, cargar el modelo
  de código descargaría al residente, que es justo lo que querías evitar).
- `persistent` solo evita que OTROS grupos descarguen a este — no fuerza precarga. Si querés
  que el residente esté cargado desde que arranca llama-swap, usá además `hooks.on_startup.preload`
  (fuera del alcance de estos comandos; se agrega a mano en el `config.yaml`).

## Presupuesto de VRAM

`check-llamaswap` calcula el **peor caso** de VRAM concurrente: por cada grupo, si `swap: true`
solo cuenta el miembro más pesado (`max`); si `swap: false`, suma todos los miembros. Los
grupos entre sí siempre se suman (se ignora `exclusive` a propósito: un grupo `exclusive: true`
solo puede REDUCIR el pico real al descargar otros grupos, nunca aumentarlo — así que sumar
todo da un límite superior seguro, que es lo que necesita un guardrail anti-OOM).

Cada modelo se estima así (**guardrail conservador, no un simulador**):

1. Si el GGUF trae metadatos de arquitectura (capas, cabezas KV, dimensión de cabeza) **y** el
   `cmd` del modelo tiene `--ctx-size` explícito → `pesos*1.05 + KV cache real` (usa
   `--cache-type-k/v` si están, default `f16`).
2. Si no → `tamaño_de_archivo * 1.2` (estimación gruesa, marcada como tal en el reporte).

Ejemplo real (16 GB de VRAM, verificado con los GGUF reales del catálogo de referencia):

| Modelo | ctx | cache KV | Estimación |
|---|---|---|---|
| `gemma3-4b` (Q4_K_M, 2.32 GiB) | 8192 | f16 | ~3.50 GiB |
| `llama31-8b` (Q4_K_M, 4.58 GiB) | 16384 | f16 | ~6.81 GiB |
| `qwen25-coder-14b` (Q4_K_M, 8.37 GiB) | 8192 | q4_0/q4_0 | ~9.21 GiB |

Con `resident=[gemma3-4b]` y `swap=[llama31-8b, qwen25-coder-14b]`: peor caso =
`3.50 + max(6.81, 9.21) = 12.71 GiB`. Con margen de sistema de 1.5 GB, el presupuesto
disponible en una GPU de 16 GB es 14.5 GiB → **cabe**, con ~1.8 GiB de margen extra.

## Presupuesto de RAM de sistema (opcional, `--ram-gb`)

VRAM no es lo único a cuidar: `llama-server` mapea el GGUF **también en RAM** (mmap) aunque el
cómputo sea 100% GPU (`-ngl` alto) — verificado en vivo, un modelo de 8.37 GiB en disco usó
~7.46 GB de RAM residente real mientras corría enteramente en la GPU. Un catálogo que cabe
holgado en VRAM puede igual acercarse al límite de RAM en una máquina con menos de 32 GB, y
ahí sí puede afectar otras ejecuciones del MCP (o del sistema en general).

Por eso `check-llamaswap`/`init-llamaswap` aceptan `--ram-gb`/`--ram-margin-gb` (default de
margen 2 GiB) — **opcional**: si no los pasás, el comportamiento es idéntico al de antes (solo
VRAM). La estimación de RAM por modelo es más simple que la de VRAM: solo pesos del archivo
(sin KV, que con offload completo vive en la GPU), marcada `method=weights-only`. Si tu `cmd`
usa `-ngl` bajo (offload parcial), la RAM real será MAYOR que esta estimación — asume offload
completo a propósito, documentado como tal.

La aritmética de peor caso por grupo es la MISMA que para VRAM (swap→max, sin-swap→suma):
cuando llama-swap descarga un modelo mata el proceso entero, liberando VRAM y RAM juntas.

Ejemplo real (mismo catálogo, verificado con `Get-Process` mientras corrían ambos a la vez):

| Modelo | RAM estimada (`weights-only`) | RAM real medida |
|---|---|---|
| `gemma3-4b` + `qwen25-coder-14b` cargados a la vez | 10.69 GiB | ~10.30 GB |

## Los dos comandos

### `check-llamaswap` — valida un config existente

```bash
local-delegate check-llamaswap --config D:\Projects\llms\llama-swap\config.yaml --vram-gb 16 --ram-gb 32
```

Imprime el desglose por grupo y modelo (VRAM, y RAM si pasaste `--ram-gb`), y termina con exit
code `0` (cabe en todo lo que se chequeó), `1` (no cabe en VRAM y/o RAM) o `2` (error de datos:
falta `groups:`, un modelo referenciado no existe, o no se pudo ubicar/leer su `.gguf`).

### `init-llamaswap` — genera/actualiza `groups` en un config existente

```bash
local-delegate init-llamaswap \
  --config D:\Projects\llms\llama-swap\config.yaml \
  --resident gemma3-4b \
  --swap llama31-8b,qwen25-coder-14b \
  --ttl-resident 600 --ttl-swap 300 \
  --vram-gb 16 --margin-gb 1.5 \
  --ram-gb 32 --ram-margin-gb 4 \
  --force
```

- Lee el `--config` existente (donde ya viven tus `cmd` de `llama-server` afinados a mano) y le
  **añade/reemplaza** la sección `groups:`, más `ttl:` en los modelos referenciados.
- Corre el/los guardrail(es) (igual que `check-llamaswap`) **antes** de escribir — si no cabe en
  VRAM o (si pasaste `--ram-gb`) en RAM, no escribe nada y sale con exit code `1`.
- `--force` es necesario para sobreescribir un `--config` que ya existe; siempre deja un
  `<config>.bak` con el contenido anterior.
- `--dry-run` imprime el YAML resultante sin tocar disco — usalo primero para revisar.
- `--add-model ID=RUTA.gguf[:VRAM_GB]` (repetible) define una entrada **mínima** de modelo si
  `ID` todavía no existe en `--config` (útil para un catálogo nuevo desde cero); el `cmd`
  generado es genérico (`--model RUTA -ngl 99`) — revisalo y ajustale flags a mano después
  (contexto, cache-type, etc.) si hace falta.

**Limitación honesta:** `init-llamaswap` usa PyYAML para reescribir el archivo, que **no
preserva comentarios ni el formato original** (los bloques `>` multilinea sobreviven como
contenido, pero pierden el formato "bonito"). Por eso el `.bak` es obligatorio al sobreescribir
— es tu red de seguridad, no una promesa de que el archivo se vea igual.

## Ritual de aplicación (recomendado, manual)

1. Backup del `config.yaml` real (aparte del `.bak` automático de `init-llamaswap`).
2. `check-llamaswap` sobre tu config actual (si ya tiene `groups:`) o corré `init-llamaswap
   --dry-run` primero para revisar el YAML antes de escribir nada.
3. Aplicá con `init-llamaswap` (sin `--dry-run`), revisá el desglose que imprime.
4. Reiniciá llama-swap.
5. Verificá con `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader`:
   - En reposo (solo el residente cargado): debería rondar la estimación del grupo `resident`.
   - En pico (forzá una delegación al modelo más pesado del grupo `swap`): debería rondar el
     total reportado por `check-llamaswap`.
6. **Rollback:** si ves OOM o VRAM usada por encima de lo esperado, restaurá el `.bak` y
   reiniciá llama-swap. No seguir insistiendo con ajustes en caliente — volver al estado
   conocido primero.

## Por qué el paquete no hace esto solo

Un `groups:` mal armado (por ejemplo `exclusive: false` en un grupo que en realidad necesitaba
excluir a otro, o subestimar el KV cache de un modelo con contexto grande) puede llevar a un
OOM de VRAM o a thrashing (el sistema operativo/driver intentando compensar swapeando memoria).
Por eso `local-delegate` **nunca** genera ni modifica `config.yaml` de motu proprio: estos
comandos existen, pero el usuario decide cuándo correrlos, revisa el desglose de VRAM antes de
aplicar, y siempre tiene un `.bak` a mano para volver atrás.
