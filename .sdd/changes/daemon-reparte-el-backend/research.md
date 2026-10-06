# Research: el daemon no se pelea por el modelo, usa el que ya está cargado, distingue espera de lentitud y la residencia es opcional

Investigación de solo lectura (2026-10-06). No se cargó ningún modelo, no se tocó la config de
llama-swap, el lanzador, el daemon ni `state.json`. `metrics.db` se consultó sobre la **copia** del
scratchpad (`scratchpad/mdb/metrics.db`, filas hasta 2026-10-06 13:50 UTC). Los scripts están en
`scratchpad/sdd-daemon/` (`velocidades.py`, `umbral_lento.py`, `roundtrip.py`, `quirurgico.py`).
El código de llama-swap v255 se leyó en `scratchpad/docs-v255/` y, para lo que faltaba, en
`scratchpad/w255/` (`llama-swap.go`, `watcher.go`, `internal/server/{server,api,apigroup}.go` de la
etiqueta `v255`, bajados con `gh api`).

## Cambios del encargo durante la investigación (2026-10-06)

1. **Ningún modelo residente, nunca.** El usuario lo aplicó ya: en `config.yaml` (11:23) desaparece el
   grupo `resident`, `gemma3-4b` pasa al grupo `swap` con los demás y su `ttl` baja de 600 a 300.
   Copia: `config.yaml.pre-sin-residente-20261006.bak`. El `diff` contra la copia son solo esas
   líneas (la edición fue quirúrgica). **Consecuencia:** ahora el modelo mecánico también choca con
   el largo y el de código; cualquier tool mecánica con el 26B cargado obliga a cambiar de modelo.
2. **Se generaliza la afinidad:** si hay un modelo cargado capaz de la tarea, se usa en vez de
   descargarlo. Matriz tool × modelo, cada celda aprobada por una evaluación con criterio escrito
   antes, y un corpus que pueda discriminar.

3. **TTL de 120 s.** Ese mismo día el usuario bajó el `ttl` de los cuatro modelos de texto de 300 a
   **120** (el 12B sigue en 30). Copia: `config.yaml.pre-ttl-120-20261006.bak`. Las cifras de esta
   investigación que dependían del TTL están corregidas abajo («Correcciones tras la revisión»).

Los tres pasan a requisitos en `spec.md`, no a preguntas abiertas.

## Current behavior

### Cómo manda hoy el daemon las llamadas al backend

- Un solo cliente `httpx2` por proceso y un semáforo de concurrencia **global**, sin noción de modelo:
  `_chat_slots = threading.BoundedSemaphore(config.MAX_CONCURRENT_REQUESTS)`
  (`src/local_delegate/server.py:113`), con `MAX_CONCURRENT_REQUESTS = 2` por defecto
  (`src/local_delegate/config.py:71`).
- Una llamada lógica toma **una plaza** en `_run_chat` (`server.py:1117`, `with _chat_slots:`) y dentro
  corre `_con_respaldo` (`server.py:986-1076`): el modelo pedido y, si falla con una clase que salta,
  los candidatos de la cadena. Cada intento real va por `_llamar_modelo` → `_post_chat`
  (`server.py:967-983`, `836`). Ese es el único punto donde se sabe **a qué modelo** va cada envío.
- Las operaciones de varios trozos (`_chat_chunked`, `server.py:1499`; `_chat_map_reduce`,
  `server.py:1687`) hacen N llamadas **en serie**, cada una tomando y soltando su plaza; el modelo de
  la operación lo fija `_ModeloVigente` (`server.py:1129-1182`), que cambia como mucho una vez
  (REQ-006 de F3).
- `inflight.json` (`server.py:125-297`) es **solo observación**: registra tool, modelo, pid y trozo de
  cada delegación de todos los procesos de la máquina para el panel (`/api/inflight`,
  `web/metrics.py:556`). No coordina nada.
- **Consecuencia medida** (`insumos/llamaswap-grupos.md` §3): dos operaciones del mismo daemon contra
  modelos distintos del grupo `swap` se intercalan trozo a trozo, y cada alternancia es un cambio de
  modelo: el 2026-10-01, `local_commit_msg` (Qwen3.6) y `local_lint_summary` (26B) hicieron **6
  cambios, 199 s**. Con `-np 1`, además, dos llamadas al mismo modelo se encolan en `llama-server`
  (~1 150 s de cola en 30 días).

### ¿Lo resuelve algo de llama-swap v255? No

- El único programador es FIFO (`docs-v255/src_fifo.go`). Tiene **vía rápida**: si el modelo pedido ya
  está listo y no hay que desalojar a nadie, se sirve en el acto aunque haya cola para otro modelo; y
  quien necesita desalojar espera a que el proceso cargado **se vacíe** (`insumos/llamaswap-grupos.md`
  §1, «Programador FIFO»). Es justo lo que permite el intercalado.
- `routing.scheduler.settings.fifo.priority` ordena solo la cola, por modelo; no adelanta lo que está
  en vuelo ni distingue clientes (`src_config.go:242`). `concurrencyLimit` limita peticiones por
  modelo, no entre modelos. El router `matrix` decide qué convive, no el orden.
- No hay ninguna API que exponga los grupos: las rutas de v255 están en
  `w255/srv_server.go:319-385` (`/running`, `/api/metrics/activity`, `/api/events`, `unload`…), y
  ninguna devuelve la configuración de grupos. **El daemon tiene que leerla del YAML.**

**Conclusión:** la serialización va en el daemon, con un cerrojo por grupo de conflicto.

### Qué significa «chocar» según v255 (sin dar por fijos los nombres)

`groupSwapper.EvictionFor` (`docs-v255/src_group.go:70-104`): al cargar `target` se desaloja a `m` si
(a) están en el mismo grupo y ese grupo tiene `swap: true`, o (b) están en grupos distintos, el de
`target` es `exclusive` y el de `m` no es `persistent`. Detalles que el lector del daemon tiene que
copiar tal cual:

- **Valores por defecto** `swap: true`, `exclusive: true`, `persistent: false`
  (`src_config.go:92-107`). Un grupo sin esas claves **sí** desaloja.
- **Los modelos sin grupo** van a un grupo `(default)` con `swap: true, exclusive: true`
  (`src_config.go:294-336`, `DEFAULT_GROUP_ID` en `:11`): chocan con todo lo no persistente.
- **Dos sintaxis**: `groups` arriba (heredada, aceptada para siempre) o
  `routing.router.settings.groups` con `routing.router.use: group`. Usar las dos es error de carga
  (`src_load.go:189-215`). Con `use: matrix` no hay grupos (`src_load.go:205-209`).
- Un modelo pertenece a un solo grupo (`src_load.go:229-243`). Los ids pueden tener **alias**
  (`src_config.go:185-186`, `RealModelName` en `:258`).

Hoy `cadenas.residente()` solo mira `groups` de arriba (`src/local_delegate/cadenas.py:69`) y no
conoce ni los valores por defecto ni la sintaxis `routing`: el lector nuevo tiene que servir a los
dos.

### La config vigente (leída, sin tocar)

`D:\Projects\llms\llama-swap\config.yaml` (LF): un solo grupo `swap`
(`swap: true, exclusive: false`) con `gemma3-4b`, `gemma4-26b-a4b`, `qwen36-35b-a3b`, `qwen35-2b` y
`gemma4-12b`, con la lista de miembros **sin sangrar** bajo `members:`; `ttl` **120** en todos salvo
`gemma4-12b` (30) desde el cambio del usuario del 2026-10-06 (antes, 300). Comentarios solo en la cabecera (que aún
hablan del «residente»). Los `cmd` son escalares entre comillas simples **plegados en varias líneas**
(estilo de volcado de PyYAML). Hay una lista con claves de API: el CLI nunca debe imprimirla.
`store.path` apunta a `metrics.db`, así que `/api/metrics/activity` está disponible.

### Qué hace `cadenas.py` sin grupo persistente

- `residente()` (`cadenas.py:53-77`): sin grupo `persistent` legible **cae al modelo del rol
  mecánico** y lo etiqueta «defecto: el modelo del rol mecánico». Con la config de hoy devuelve
  `gemma3-4b`. `local_status` (`server.py:3072` → `cadenas.describir`, `cadenas.py:112-124`) y
  `doctor` (`checks.py:1363-1364`, «cadenas válidas; residente gemma3-4b (…)») **siguen hablando de
  un residente que no existe**.
- Cadenas por defecto (`cadenas.py:37-41`): `code → residente → long`, `long → residente → code`,
  `mechanical → long`. Con `gemma3-4b` en el grupo `swap`, saltar al «residente» **ya no es gratis**:
  descarga el modelo que falló y carga el 4B (~6 s), para dar una respuesta de calidad menor.
- REQ-018 de F3 (`delegacion-precisa-y-fiable/spec.md:353-355`, aplicado en `server.py:1037-1055`):
  un fallo **de capacidad** solo salta al residente «que ya está en memoria y no obliga a cargar
  nada». Sin residente, ese salto carga un modelo: contradice su propia razón de ser.
- La decisión D-4 de F3 («el primer respaldo del rol de código es el mecánico»,
  `delegacion-precisa-y-fiable/spec.md:529-533`) se justificaba porque el primer salto era «sin
  swap». Esa premisa cae. Además, la regla nueva del usuario prohíbe delegar código o largo al
  mecánico.
- **Propuesta (va a la spec):** el paso `residente` pasa a significar **«el modelo cargado»**
  (`cargado`): se resuelve en el momento del salto al modelo que esté cargado, si su celda de la
  matriz está aprobada para esa tool y no es el que falló; si no, se salta. Conserva el espíritu de
  REQ-018 (saltar solo a lo que no hay que cargar) y respeta «nunca al mecánico». `residente` en las
  variables se sigue aceptando como sinónimo, con aviso en `doctor`.

### Velocidades y contexto por modelo (copia de `metrics.db`, desde 2026-09-15 19:26 UTC)

| Modelo | Contexto (`--ctx-size`) | Tope del rol (`MAX_CHARS`) | Prefill mediana (entrada ≥ 1 000 tok) | Generación mediana | Carga en frío (insumo) |
| --- | --- | --- | --- | --- | --- |
| `gemma3-4b` (mecánico) | 8 192 | 20 000 | 3 954 tok/s (n=16) | 104,9 tok/s (n=27) | ~6 s |
| `gemma4-26b-a4b` (largo) | 38 400 | 48 000 | 1 050 tok/s (n=223) | 40,5 tok/s (n=239) | ~14 s |
| `qwen36-35b-a3b` (código) | 16 384 | 20 000 | 481 tok/s (n=61) | 40,5 tok/s (n=71) | ~14 s |
| `gemma4-12b` (visión) | 8 192 + mmproj | — | 1 190 tok/s (n=3) | 46,8 tok/s (n=12) | — |

Fuentes: `scratchpad/sdd-daemon/velocidades.py`; contextos de `config.yaml`; topes de
`config.py:238-243`. **La verbosidad no se puede sacar de `metrics.db`**: la mediana de tokens de
salida (4B 211, 26B 511, Qwen 185) mide tareas distintas, no el mismo prompt. Se mide en la
evaluación con los mismos casos.

Lo que eso implica para la afinidad:

- **Mecánico sobre el 26B cargado**: una clasificación (≈100 tok de entrada, ≈5 de salida) cuesta
  décimas en los dos; un resumen corto (≈1 500 tok, ≈250 de salida) son ≈6,6 s en el 26B frente a
  ≈2,8 s en el 4B **más ~6 s de cargarlo**, y más ~14 s si luego vuelve una tarea larga. Gana el 26B
  casi siempre.
- **Contexto y troceado**: si la operación conserva el tope **de su rol** (`max_chars_for_role`), el
  troceado es idéntico en los dos modelos y lo medido en la evaluación es lo que corre en producción.
  El 26B admite más (38 400), así que conservar el tope del rol nunca lo desborda. Al revés no: una
  tarea del rol largo (48 000 chars) no cabe en Qwen3.6 (16 384 tokens), y la densidad chars/token
  varía el doble (memoria `presupuesto-en-chars-limite-en-tokens`); el filtro de REQ-003 de F3
  (`max_chars_for(candidato)`, `config.py:260-268`) ya lo impide para los saltos.
- **Coste no evidente**: usar el 26B para tareas mecánicas le reinicia el TTL, así que se queda
  cargado hasta 120 s más (11,7 GB de RAM del sistema). Es lo mismo que pasa tras cualquier llamada
  larga, pero conviene que el usuario lo sepa (quiere la VRAM libre para jugar).

### ¿Qué velocidad se toma por «normal»?

Respuesta: **la mediana móvil del propio log de uso**, por modelo, no `metrics.db` ni un valor
declarado:

- `metrics.db` es de otro programa (esquema de llama-swap), no existe en la Mac y mezcla todos los
  clientes; un valor declarado se queda viejo en cuanto cambia un `-ncmoe`.
- La respuesta de `llama-server` trae `timings` (`prompt_n`, `prompt_ms`, `prompt_per_second`,
  `predicted_n`, `predicted_ms`, `predicted_per_second`): llama-swap los lee del cuerpo para
  `metrics.db` (`docs-v255/src_metrics.go:226-237`, `:467-481`) y nuestro `benchmark.py` ya los
  guarda (`src/local_delegate/benchmark.py:1136`; aparecen en
  `benchmarks/catalogo-2026-09/resultados/cp3-*.jsonl`). `_post_chat` hoy los descarta
  (`server.py:859-867` solo toma `usage`).
- Se compara **solo la generación**: la primera petición tras cargar con `mmap` tiene el prefill lento
  y es normal (`insumos/llamaswap-grupos.md` §3, fila 570).
- **Umbral 0,5 de la mediana**, contrastado sobre la copia de `metrics.db`
  (`scratchpad/sdd-daemon/umbral_lento.py`): marca 9 de 349 filas (2,6 %): las 570, 571 y 573 del
  2026-09-30 (Qwen3.6 a 10,0 / 6,8 / 8,1 tok/s), la 615 (5,0) y tres del 26B el 2026-10-01 13:48–13:50
  (14,6–16,6). La 574 (20,4 tok/s = 50,4 %) se queda fuera: por eso el log guarda la **razón**, no
  solo la marca. Con 0,6 serían 20 filas e incluiría un racimo de 26B y Qwen3.6 lentos el
  2026-10-01 13:34–13:53, **un segundo episodio** que nadie había visto.
  **Límite (hallazgo 8 de la revisión):** ese script usa la mediana de **toda la ventana** y filas de
  **todos los orígenes**, no la regla de la spec (ventana móvil de 50 eventos propios, mínimo 10), y
  las filas 570, 571 y 573 son de la Mac, que el daemon de la PC no ve. Sirve de orientación. El
  control de la spec repite la regla exacta sobre las filas de la PC y usa las de la Mac solo como
  control positivo de la regla.
- La RAM libre (`web/sysinfo.py:28`, `ram_stats()` con `GlobalMemoryStatusEx`) solo tiene sentido si
  el backend es **local**: en la Mac mediría la RAM de la Mac.

### Cómo sabe el daemon qué está cargado, y la carrera con el TTL

- `GET /running` (`w255/srv_api.go:350-369`) devuelve por modelo `state` (`ready`, `starting`…) y el
  `ttl` **configurado**, pero **no** cuándo se usó por última vez. El daemon ya lo consulta con la key
  (`_estado_en_llamaswap`, `server.py:758-779`, tope de 1 s).
- La última actividad sale de `GET /api/metrics/activity?model=<id>&limit=1`
  (`w255/srv_apigroup.go:162-176`, `232-262`): filtra por modelo y requiere `store` configurado. La
  fila se escribe **al terminar** la petición, así que no ve lo que está en vuelo.
- El propio daemon sí sabe lo que **él** tiene en vuelo (su cerrojo): eso es certeza, sin red.
- **La carrera**: si el modelo cargado vence su TTL entre la consulta y la petición, se cargaría el
  grande en lugar del pequeño, que es peor. ~~Se cerraba con un margen de 60 s~~: **corregido** en
  «Correcciones tras la revisión», con lo que la v255 expone de verdad (`/api/events`) y cómo cuenta
  el TTL (`process_command.go`). El margen pasa a 5 s.

### `-watch-config`: qué pasa al escribir el YAML

- El vigilante sondea cada **2 s** y dispara si cambia la `mtime` o el **tamaño**
  (`w255/watcher.go:17`, `:84`).
- La recarga (`w255/llama-swap.go:306-389`) parsea el fichero nuevo; **si no valida, lo avisa y se
  queda con la config vieja** (`:322-330`). Si valida, construye un servidor nuevo, cambia el activo y
  apaga el viejo con `Shutdown(30 s)` (`:375`), que apaga sus routers y procesos
  (`w255/srv_server.go:495-520`): **todos los modelos cargados se descargan** en cada recarga.
- Consecuencias: (1) escribir en dos pasos puede disparar una recarga a medio escribir → hay que
  reemplazar el fichero de forma atómica; (2) un YAML roto no tumba lo que corre, pero sí el próximo
  arranque → hay que validarlo antes de reemplazar; (3) escribir con delegaciones en curso las
  expone al apagado del servidor viejo (espera hasta 30 s): **no verificado si se cortan**; se
  comprueba en la tarea de prueba con un llama-swap de prueba y un servidor falso (sin modelos).

### Librería YAML: ¿conservar comentarios y formato?

| Opción | Depscore Socket | Resultado sobre una copia de la config vigente |
| --- | --- | --- |
| `ruamel.yaml` 0.19.1 (nueva; puro Python, sin dependencias obligatorias según PyPI) | license 100, maintenance 100, quality 100, **supplyChain 99**, vulnerability 100 | **No conserva el formato.** Ida y vuelta sin cambios: **38 líneas distintas** con ancho 80 y 26 con ancho 4096: re-pliega los `cmd` entre comillas y cambia la sangría de la lista de claves (`  - ` → `- `). La sangría de listas es global en ruamel y este fichero mezcla dos estilos, así que no tiene arreglo por opciones (`scratchpad/sdd-daemon/roundtrip.py`). |
| `ruamel.yaml.clib` 0.2.15 (solo con el extra `oldlibyaml`) | quality 90, resto 100 | No hace falta. |
| **PyYAML 6.0.3** (ya está en el extra `[llamaswap]`, `pyproject.toml:67`) + **edición quirúrgica** con las marcas de posición de `yaml.compose()` | todo 100 | Cambiar `models.gemma3-4b.ttl` reemplazando solo el tramo del escalar: **1 línea distinta** (la 24), el resto byte a byte, y `safe_load(resultado) == original + cambio` → `True` (`scratchpad/sdd-daemon/quirurgico.py`). |

**Recomendación: no añadir dependencia.** Todas pasan el 0,7, pero ruamel falla en lo que importa
(conservar el fichero). La edición quirúrgica con PyYAML ya está instalada, deja intacto todo lo que
no se cambia y se autocomprueba: el resultado parseado tiene que ser **exactamente** el original más
el cambio pedido, o no se escribe. Límite: los nodos en estilo flujo (`{…}`, `[…]`) se rechazan con un
mensaje en vez de editarlos. La edición del usuario de hoy fue de este tipo (diff mínimo).

`llamaswap_config.dump_config` (`llamaswap_config.py:363-371`) reescribe todo con PyYAML y lo
reconoce en su docstring; `init-llamaswap` lo usa con un `.bak` fijo (`cli.py:573-578`) que se pisa
en cada ejecución. El CLI nuevo no debe reutilizarlo para editar.

### Corpus y criterio de F2 para aprobar celdas de la matriz

- **Corpus de F2**: `benchmarks/catalogo-2026-09/cases.json`, construido por
  `scripts/construir_corpus.py`, que **captura** rol y número de llamadas llamando a la tool real con
  el backend interceptado; cada caso lleva el `system`/`user_template` de producción.
- **Casos de `local_commit_msg`**: solo **uno de calidad**, `commit-diff-19k` (git show 4d644ae, 19 041
  chars, `automatic_scoring: false`: la cobertura de términos no discriminaba y pasó a revisión a
  ciegas, `protocolo-f2.md:523-527`), y un techo, `techo-commit-156k` (13 llamadas en producción).
  Cinco corridas de un solo caso dan 5 pares: la prueba de signos solo concluye con 5 a 0. **No
  basta**: hay que ampliar el corpus.
- **Casos mecánicos de F2** (`resumen-md-2k`, `extraer-toml-2k`, `clasificar-53`, `traducir-42`,
  `delegar-56`): los cinco en **techo** con los dos modelos medidos (`verification.md:746`, «la regla
  no puede disparar», `:760`). Un caso donde todos aciertan no valida nada: sirven de regresión, no
  de prueba.
- **Criterio de F2 para cambiar el modelo de un rol** (`verification.md:653-772`): comparación por
  pares a ciegas (`scripts/hoja_pares.py`) con prueba de signos, `veredicto_pares` y `ALFA_PARES =
  0,05` (`scripts/analizar_benchmark.py:60`, `:311-325`). Es un criterio de **superioridad**; para la
  afinidad hace falta uno de **no inferioridad** (el cargado no puede ser peor), escrito en la spec.
- Controles de F2 reutilizables: `reference_ok`/`reference_bad` por caso (el puntuador tiene que dar
  1 al bueno y menos al malo, CP-4) y `qwen35-2b` como modelo débil del catálogo, sin rol.
- **Hallazgo de F2 que la evaluación tiene que poder ver**: `qwen25-coder-14b` «se quedó con el bump
  de versión y omitió el arreglo» en `commit-diff-19k` (`protocolo-f2.md:525-527`): un mensaje de una
  línea puede tener formato perfecto y estar mal. Por eso commit_msg necesita juicio humano.

### Quién llama al backend en esta máquina

El daemon HTTP (`daemon.py:1-7`) sirve Claude Code y Codex desde un proceso. Cualquier otro proceso
(una instancia stdio de Claude Desktop, que el instalador no toca; `benchmark.py`) llama a llama-swap
por su cuenta: un cerrojo **en memoria** del daemon no los ve. Lo mismo con la Mac, que es otro
daemon. `inflight.json` sí ve todos los procesos de la máquina, pero coordinar a través de un fichero
añade bloqueos de disco en el camino de cada llamada; queda fuera de este cambio.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| Lector de topología (nuevo, junto a `llamaswap_config.py`) | — | Lee grupos (dos sintaxis, valores por defecto, `(default)`, alias, `--mmproj`, `ttl`, `globalTTL`) y responde «¿chocan A y B?» | `src_group.go:70-104`, `src_config.go:92-107,294-336`, `src_load.go:189-243` |
| `server.py` `_run_chat` / `_chat*` / `_con_respaldo` | Plaza global, respaldo | Turno por grupo de conflicto por **operación**, antes de la plaza; decisión de afinidad al obtener el turno | `server.py:1079-1126`, `986-1076`, `1129-1182`, `1499`, `1687` |
| `server.py` `_post_chat` / `ChatResult` | Texto, `usage` | Conservar `timings` | `server.py:647-656`, `836-867` |
| `server.py` `_log_event` | Línea JSONL | Campos aditivos: espera, turno, ritmo, lento, RAM, afinidad | `server.py:453-560` |
| `server.py` `local_status` | Roles, cadenas, `/running` | Turno, afinidad, residencia, medianas de referencia | `server.py:3042-3124` |
| `cadenas.py` | Residente = grupo `persistent` o mecánico | `cargado` en vez de `residente`; textos sin residente fantasma | `cadenas.py:53-124` |
| `checks.py` `_probe_fallback` | «residente X» | Texto nuevo; check de topología y de residencia | `checks.py:1340-1364` |
| `config.py` | Variables | Variables nuevas por los helpers `_env*` (inventario) | `config.py:39-60`, `71`, `283-297` |
| `cli.py` + `llamaswap_config.py` | `check-llamaswap`, `init-llamaswap` (reescribe con PyYAML, `.bak` fijo) | Comando de residencia y TTL con edición quirúrgica; `init-llamaswap` deja de recomendar residente | `cli.py:417-578`, `llamaswap_config.py:346-371` |
| `web/metrics.py` + espejo JS | Panel, `/api/inflight`, `/api/backend` | Espera/inferencia/lento por llamada; «esperando turno» en curso; afinidad | `web/metrics.py:556-600`, `1491-1578` |
| `benchmarks/` + `scripts/` | Corpus y análisis de F2 | Corpus de afinidad, veredicto por celda | `scripts/construir_corpus.py`, `hoja_pares.py`, `analizar_benchmark.py:291-352` |
| Docs | README, wiki | Sin residente recomendado; matriz; campos nuevos | `README.md:257-264`, `docs/wiki/Configuration.md:67-83`, `Integration-install.md:202`, `Tools.md:215`, `Architecture.md:144`, `docs/recipes/llama-swap-groups.md` |

## Existing conventions

- Toda variable nueva entra por los helpers `_env*` de `config.py`; `tests/test_aislamiento_entorno.py`
  lo vigila. Lo que se lee en caliente (como `LLAMASWAP_CONFIG`, `config.py:292-297`) se lee al llamar.
- Observar no rompe una tool: el log, `inflight` y las sondas son best-effort (`server.py:174-204`,
  `816-819`). Un fallo leyendo la topología o `/running` degrada al comportamiento de hoy.
- Campos del log **aditivos y omitidos** cuando no hay dato (`server.py:483-485`, `515-527`).
- Dos fuentes para el mismo dato van atadas por un test (espejo JS del panel y su test de paridad).
- Los criterios de evaluación se escriben antes de medir y cada control nombra la tarea que produce sus
  insumos (`.sdd/changes/panel-dice-la-verdad/spec.md`, memoria «un control que no puede dar un
  resultado distinto no es un control»).
- Mutantes que hacen fallar el test **por el assert correcto**; probar el uso, no la pieza.
- Comandos pesados con `bash ~/.claude/scripts/pesado.sh`, `pytest` incluido.
- El repo mezcla LF y CRLF fichero a fichero: el CLI conserva el fin de línea del YAML.
- Una release toca CHANGELOG, README y `docs/wiki/`.

## Dependencies and integrations

- **llama-swap v255** en `127.0.0.1:9292`, `-watch-config`, config en `LLAMASWAP_CONFIG` (la pone el
  lanzador del daemon). API usada: `/running`, `/api/events` (solo la carga inicial),
  `/api/metrics/activity` (con `store`) y, para el CLI, la suscripción a `/api/events`; todo con la
  key, que solo tiene el daemon.
- **PyYAML** (extra `[llamaswap]`, ya instalado en el daemon de esta PC). Sin el extra, no hay
  topología: no hay turno ni afinidad, y `doctor` lo dice.
- **Sin dependencias nuevas.** `ruamel.yaml` descartada por evidencia, no por puntuación.
- La Mac no tiene `LLAMASWAP_CONFIG` (backend remoto): sin turno y, por decisión del usuario (la Mac
  queda fuera de alcance), también sin afinidad.
- **Cambio previo**: `panel-cuentas-y-estados-honestos` toca `server.py`, `web/metrics.py` (y su espejo
  JS), `checks.py`, `fallos.py`, `tests/test_captura.py`, `tests/test_aislamiento_entorno.py`,
  `tests/test_metrics.py`, `tests/backend_mock.py`, `docs/wiki/Savings-and-metrics.md`. Este cambio se
  implementa **después** de que se mezcle.

## Risks and unknowns

**Hechos confirmados**

- El intercalado viene del daemon y llama-swap no ofrece cómo evitarlo.
- `ruamel.yaml` no conserva este fichero; la edición quirúrgica con PyYAML sí.
- Una recarga de llama-swap descarga todos los modelos.
- `cadenas.py` y `doctor` nombran un residente que ya no existe.

**Supuestos que hay que validar (con la tarea que lo hace en el plan)**

- Que las delegaciones en curso **se cortan** o no al recargar llama-swap: prueba con un llama-swap
  v255 de prueba en otro puerto y un servidor falso en Python como `cmd` (no carga modelos).
- ~~Que `/api/metrics/activity` devuelve primero la fila más reciente~~: **confirmado en el código**
  (`internal/store/store.go`, `activityOrderBy`: por defecto `ORDER BY id DESC`).
- Que el TTL cuenta desde el final de la última petición y se congela con peticiones en vuelo:
  **leído en el código** (ver «Correcciones tras la revisión»); la prueba de llama-swap lo comprueba
  en ejecución.
- Que el 26B es igual de válido que el 4B en tareas mecánicas, y que en commit_msg no es peor que
  Qwen3.6: lo decide la evaluación de la spec, que puede salir en contra.
- Que solo el daemon llama al backend en esta PC durante el trabajo normal: si una instancia stdio
  de Claude Desktop delega a la vez, el cerrojo no la ve (riesgo residual aceptado; ver Non-goals).
- La espera del turno puede ser larga (una operación de 13 trozos son minutos). Hoy esa espera ya
  existe, repartida y con cambios de modelo; con el turno se concentra. Por eso hay tope y se
  muestra en el panel.

## Correcciones tras la revisión de la spec (2026-10-06)

Investigación añadida para responder a `review.md` («Revisión de la spec»). Fuentes nuevas, bajadas
de la etiqueta `v255` con `gh api` a `scratchpad/ls255v2/`: `internal/process/process_command.go`,
`internal/store/store.go` e `internal/logmon/logging.go`. Lo demás, de `scratchpad/ls255/` y
`scratchpad/w255/`. Scripts nuevos en `scratchpad/sdd-daemon/` (`esquema.py`, `recargas_ttl.py`).

### Cómo cuenta el TTL la v255 (hallazgos 3 y 4)

- `ProcessCommand` guarda `lastUse`, la hora a la que **termina** cada `ServeHTTP`
  (`process_command.go:132`, `:804-807`), e `inflight`, cuántas peticiones están dentro del proceso.
- El TTL lo vigila una gorrutina con un tic de **1 s** (`:344-364`): si hay alguna petición en vuelo,
  no hace nada (`if p.inflight.Load() != 0 { continue }`); si no, descarga cuando
  `time.Since(lastUse) > ttl`.
- Consecuencias:
  1. un modelo con una petición en vuelo, de quien sea, **no se descarga por TTL** mientras dure;
  2. tras la última petición le quedan exactamente `ttl` segundos, más un tic;
  3. la carrera solo existe entre el cálculo y la entrada de la petición en el proceso. Si la decisión
     se toma con la plaza ya obtenida, justo antes de enviar, son milisegundos.
- `ts_created` de la actividad es un entero en segundos (`store.go`: el filtro compara con
  `Start.Unix()`). Truncar hace que la última actividad parezca anterior y el TTL restante, menor: es
  el lado prudente. La fila se escribe después de que termine `ServeHTTP`, así que no puede ser
  anterior a `lastUse`; como mucho, posterior por milisegundos.
- **Margen resultante: 5 s** (tic de 1 s + holgura para las tres consultas de 1 s como tope + 1 s). La
  prueba con el llama-swap de prueba mide la ventana real antes de implementar la afinidad. Con TTL
  120, el cargado sirve 115 s de cada 120. El margen de 60 s de la primera versión lo dejaba inservible
  pasado su primer minuto, que es lo que señaló el usuario.

### Qué expone la v255 para saber qué está cargado y qué está en vuelo

- `GET /api/events` (SSE, `internal/server/apigroup.go:495-602`) manda al conectar, en este orden:
  el historial del log del proxy y el de los procesos (hasta 100 KB cada uno, `logging.go:100`),
  `modelStatus`, `uiConfig`, `profileChanged` y **`inflight`**: la foto de **todas** las peticiones en
  vuelo (`s.inflight.Current()`), de cualquier cliente, con `model` (id real), `timestamp` y
  `elapsed_ms` (`swaputil/events.go`).
- **Matiz que corrige la revisión:** el rastreador de peticiones en vuelo las registra en el
  middleware, **antes** de la cola del router (`inflight.go:380-395`). Una petición en vuelo para Y no
  significa que Y esté cargado: puede estar esperando a que Y se cargue. Por eso la spec exige `ready`
  en `/running`, y trata una petición en vuelo para un modelo que choca y no está `ready` como un
  cambio de modelo pendiente de otro cliente.
- `GET /running` (`api.go:350-369`) da estado, TTL efectivo y **`cmd`**: el daemon no debe registrarlo
  ni devolverlo. No da la última actividad.
- No hay ninguna ruta que exponga la última actividad sin `store`, ni una ruta JSON simple de
  peticiones en vuelo: la foto solo sale de `/api/events`.
- Una suscripción permanente a `/api/events` daría todo en tiempo real, pero el emisor descarta
  mensajes si el búfer se llena (`apigroup.go:509-546`) sin avisar al cliente, y cada línea de log es
  un mensaje. Se descarta: la foto puntual, con un tope de 1 s, es más simple y no se desincroniza.

### Cuántas cargas en frío de más trae el TTL de 120 (hallazgo menor 26)

`scratchpad/sdd-daemon/recargas_ttl.py` repite las 360 peticiones de la copia de `metrics.db` desde el
2026-09-15 19:26 UTC (20,8 días) con la topología de hoy (un solo grupo `swap`) y la regla de TTL de la
v255, con TTL 300 y con TTL 120 para los de texto (visión en 30 en los dos):

| Modelo | Cargas en frío con TTL 300 | Con TTL 120 | De más | Coste (carga mediana) |
| --- | --- | --- | --- | --- |
| `gemma3-4b` | 22 | 22 | 0 | 0 s |
| `gemma4-26b-a4b` | 73 | 76 | 3 | ~42 s |
| `qwen36-35b-a3b` | 33 | 35 | 2 | ~28 s |
| `gemma4-12b` | 8 | 8 | 0 | — |

**5 cargas de más en 20,8 días, unos 70 s**: casi todas las cargas en frío vienen ya de los cambios de
modelo o de pausas de más de 300 s. Es una reconstrucción a partir de las horas de inicio y fin
(±1 s), no una medición.

### Recarga de la config: cómo distinguir las tres salidas (hallazgo 12c)

- La recarga (`w255/llama-swap.go:305-389`) escribe en el log del proxy «reloading configuration» al
  empezar. Después escribe «failed to reload config: …» o «failed to build new server during
  reload: …» si **rechaza**, y sigue con la vieja; o «configuration reloaded» si **recarga**, después
  de apagar el servidor viejo con `shutdownTimeout` = 30 s (`:42`).
- El vigilante sondea cada 2 s (`watcher.go:17`). Si en 10 s no aparece «reloading configuration»,
  llama-swap no vigila el fichero.
- Por defecto el log **no lleva hora** (`logTimeFormat: ""`, `logging.go:228-238`), así que releer
  `/logs` no permite saber qué líneas son posteriores a la escritura. Por eso la vigía se **suscribe**
  a `/api/events` antes de escribir y solo mira lo que llega después de la carga inicial.
- Todo eso exige la key. En esta PC vive en el lanzador del daemon (memoria «verificación contra el
  backend real»: nunca pedírsela al usuario), así que la vigía corre en el daemon, como ya hace
  `doctor` cuando le pregunta por el backend (`config.web_auth_headers`).

### Estimador de VRAM con `-ncmoe` (hallazgo 11)

`estimate_model_vram` (`llamaswap_config.py:198-253`) suma pesos × 1,05 más KV y no lee `-ncmoe`. Ya
admite `override_gb`. Con `-ncmoe N`, llama.cpp deja en la CPU los tensores de expertos de las
primeras N capas. Sus bytes se pueden sacar de la tabla de tensores del GGUF por diferencia de
offsets, sin tabla de tipos. La cifra se valida contra lo medido en F2 antes de fiarse de ella.
Mientras tanto, `--vram-modelo` lleva al estimador las cifras medidas.

### Plazos, cancelación y temperatura

- `HTTP_TIMEOUT` = 180 s por defecto, pero configurable con `LOCAL_DELEGATE_TIMEOUT` (`config.py:68`),
  y puede pasar de 600. Por eso (segunda pasada de la revisión) el reloj de la red de seguridad no
  cuenta el tiempo con llamadas en vuelo: así no depende de ningún valor de `HTTP_TIMEOUT`.
- La cancelación del cliente no llega al hilo de la tool con `mcp` 2.2.0 (`anyio.to_thread.run_sync`
  sin `abandon_on_cancel`, `func_metadata.py:164`, comprobado por la revisión).
- Temperaturas de producción: `local_classify` y `local_extract` a 0,0 (`server.py:2310`, `:2359`),
  `local_boilerplate` a 0,1, `local_commit_msg` a 0,2 y el resto al 0,2 por defecto de `_chat*`. El
  payload no lleva semilla. A temperatura 0, repetir corridas da la misma respuesta. Por eso la
  evaluación usa más casos distintos y una corrida por caso.
- La regla de selección de commits para el corpus da **104 candidatos** entre los últimos 400 commits
  de `main` (sin merges, sin Dependabot ni `chore(deps)`, sin `chore: release`, diff de 2 000 a 20 000
  chars). Sobran para 29.
- No se comprobó qué plazo aplican Claude Code y Codex a una tool MCP. Queda como tarea del plan.

## Llamadas `local_*`

**0.** Se cargaron `local_summarize`, `local_extract` y `local_explain_code` como pedía el encargo, pero
no se usaron:

- **Desde hoy no hay residente**: cualquier llamada habría descargado lo que estuviera cargado y
  montado otro modelo, justo el efecto que este cambio quiere evitar, y habría añadido filas a
  `metrics.db`, que se estaba midiendo.
- Lo que había que leer necesitaba el **texto literal** para citar `fichero:línea` (brief, insumo,
  código de llama-swap, criterios de F2). Los ficheros grandes (`protocolo-f2.md` de 171 KB,
  `verification.md` de 94 KB, `server.py`) se consultaron con `Grep` y lecturas por franjas.
