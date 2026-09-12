# Research: cadena de respaldo entre modelos locales y enfriamiento temporal por modelo

Dos investigaciones del 2026-09-11: el mapa de impacto del código (lectura de `src/` y `tests/`, con
fichero:línea) y el diseño de OmniRoute (`diegosouzapw/OmniRoute`, MIT), del que se toma **el diseño,
no el código**. Rutas relativas a `src/local_delegate/` salvo que se diga otra cosa.

## Current behavior

- **Un modelo por rol, sin alternativa.** `config.py:208-217` fija mecánico `gemma3-4b`, largo
  `llama31-8b`, código `qwen25-coder-14b`, rápido `qwen35-2b` y visión `qwen3-vl-8b`. Si el modelo
  elegido falla, la tool devuelve `[local-delegate error]` y el trabajo recae en el agente principal,
  que es justo el gasto que local-delegate existe para evitar.
- **Un único punto por el que pasan todas las llamadas:** `_run_chat` (`server.py:681-722`). Lo usan
  `_chat` (768), `_chat_chunked` (1048) y `_chat_map_reduce` (1212). Llama a `_post_chat` (712) dentro
  del semáforo `_chat_slots` (711) y ya tiene un reintento propio: sin `response_format` ante un 400
  (714-721).
- **Clasificación de errores de `_post_chat` (`server.py:593-663`):**
  - `connect_error`: autoarranque o pregunta por elicitation, y un segundo intento.
  - `http_<código>`: sin distinguir 4xx de 5xx (638-646).
  - `http_error`: el resto del transporte (647-652).
  - `bad_response`: JSON roto (653-658).
- **Defectos que el cambio destapa** (verificados leyendo el código):
  - `choice["message"]["content"].strip()` (605) lanza `AttributeError` con `content: null`, que no se
    captura: sale de la tool como excepción y un respaldo basado en `ChatResult` no lo vería.
  - Un `ConnectTimeout` no es `ConnectError`: cae en `http_error` y no dispara ni el autoarranque ni
    la pregunta. Un `ReadTimeout` también cae en `http_error`, tras esperar hasta `LOCAL_DELEGATE_TIMEOUT`
    (180 s por defecto, `config.py:68`).
  - `retry_exhausted` (659-663) es inalcanzable.
- **El desborde de contexto llega como HTTP 400** y se detecta por el texto (`_es_desborde_de_contexto`,
  1140-1165). Solo lo trata map-reduce, partiendo el trozo (1252-1277).
- **La entrada se recorta con el límite del modelo original** antes de llamar: extract (1555), translate
  (1937) y explain (1976). Los límites están en `MAX_CHARS` (`config.py:224-229`): mecánico 20000,
  largo 48000, código 20000 y rápido 12000. Un respaldo con menos contexto se desbordaría.

## Impact map

| Area | Current responsibility | Expected impact | Evidence |
| --- | --- | --- | --- |
| `_run_chat` | una llamada bajo el semáforo, reintento de schema | punto de inserción del respaldo, después del reintento de schema y sin cambiar la firma de `_post_chat` | `server.py:681-722` |
| `_post_chat` | POST y clasificación de errores | separar fallo del endpoint, de la petición y del modelo; capturar `content: null` y `ConnectTimeout` | `server.py:593-663`, 605 |
| `config.py` | variables de rol y límites | variables nuevas registradas en `VARIABLES_DE_ENTORNO` y leídas con `_leer`/`_env*` | `config.py:208-234`, 331 |
| Estado compartido | `inflight.json` con `FileLock`, escritura atómica, limpieza por pid/antigüedad | fichero hermano para el enfriamiento, con marcas de reloj real (`time.time()`) | `server.py:114-126`, 165-215, 232 |
| Log y panel | `_log_event` guarda el modelo **pedido**; el panel agrupa por él | campo del modelo que respondió; atribución correcta en `web/metrics.py`; `chunks` cuenta las llamadas extra | `server.py:429-517`, 481-485; `web/metrics.py:223-295` |
| `local_status` | catálogo y estado del backend | mostrar los modelos en enfriamiento y hasta cuándo | `server.py:2230-2239` |
| Tests | `backend_mock.py` reconoce rutas por método+URL, no por `model` | un doble que responda según el `model` de la petición; fixture si hay estado en memoria | `tests/backend_mock.py:62-63`, 108; `tests/conftest.py:29-41` |
| Docs | README, `docs/wiki/Configuration.md`, `Architecture.md`, `Tools.md`, `Troubleshooting.md`, `Savings-and-metrics.md`, CHANGELOG, skill `delegacion-local` | documentar variables y comportamiento | informe del mapa, sección 6 |

## Existing conventions

- **«Preguntar nunca puede empeorar nada»** (change `elicitation-preguntar-en-vez-de-fallar`): todo
  camino malo degrada al comportamiento de hoy. El respaldo hereda la regla: **si no hay candidato
  válido, el resultado es exactamente el error de hoy**.
- **Backend opt-in** (`server.py:616-618`): nada se arranca sin permiso.
- **`chunks` son llamadas reales al backend** (change `contabilidad-chunking`, `server.py:481-485`).
- **El paquete no toca `config.yaml` de llama-swap** (receta `docs/recipes/llama-swap-groups.md:169-176`).
- **Variables de entorno autoinventariadas** en `config.VARIABLES_DE_ENTORNO`;
  `tests/test_aislamiento_entorno.py` falla si una se lee por otra vía.
- **Nada sale del endpoint configurado** (`open_world_hint=False`, `server.py:83-86`).

## Dependencies and integrations

- **llama-swap decide qué modelo está en VRAM.** Con la receta de grupos, `gemma3-4b` es residente y
  los modelos del grupo `swap` se expulsan entre sí (`docs/recipes/llama-swap-groups.md:36-47`, 84-86).
  - Cambiar a un modelo no cargado cuesta segundos de carga.
  - Además **puede expulsar el modelo que usa otra petición u otra sesión**.
  - El único respaldo barato es el residente.
- En ejecución, el paquete solo sabe qué está cargado vía `/running` (`server.py:2187`) y `/v1/models`
  (2169); hoy no lo usa para elegir modelo.
- **Modelo de procesos:** el daemon único es el recomendado (`daemon.py`), pero sigue existiendo el modo
  stdio, uno por cliente (`entrypoint.py:65-82`). Un estado solo en memoria no se compartiría entre ellos.
- Sin dependencias nuevas: `filelock` ya se usa para `inflight.json`.
- **Coordinación con la sesión que investiga modelos nuevos** (`local-delegate-44`, 2026-09-11; nota del
  vault `projects/llms/investigacion-modelos-abiertos-2026-09.md`). No toca el repo, pero:
  - **Los modelos por defecto y el residente probablemente cambien.** Hay candidatos para todos los
    roles, entre ellos MoE de 13 a 18 GB, y se baraja consolidar largo, código y visión en un solo
    modelo. Por eso las cadenas se declaran por rol y se deduplican (REQ-004).
  - **La política «Prefer No Sysmem Fallback»** convierte un modelo que no cabe en un error de carga u
    OOM, en vez de lentitud. Eso separa la clase «capacidad o carga» (REQ-018).
  - **Los MoE con `--n-cpu-moe` tardan más en montar:** un timeout de carga no es un fallo del modelo.
  - **Modelos de razonamiento:** `gpt-oss-20b` devolvió `content` vacío en el canary de julio porque el
    razonamiento agotó `max_tokens` (REQ-019).
  - **Benchmarks:** un salto en mitad de una medición contamina VRAM y tok/s. Hacen falta un interruptor
    y la marca en el panel (REQ-013, REQ-014).
  - **VRAM:** el residente más un modelo de 13–14 GB no caben juntos en 16 GB, así que un segundo salto a
    un modelo grande siempre expulsa algo.

## Lecciones de OmniRoute (diseño, no código)

- **Tres capas separadas:** clasificar el error, decidir si se salta, y llevar el estado de salud del
  modelo. Sus bugs de «baneado para siempre» (#12859, #13157) no vinieron del circuit breaker sino de la
  **clasificación**: una variante de error no prevista caía en el peor caso (terminal). Aquí, lo no
  clasificado debe caer en el caso **menos dañino**: no penalizar al modelo.
- **Errores de la petición no penalizan al modelo:** el desborde de contexto, un 400 genérico y los
  timeouts provocados por el propio sistema (`isSelfInflictedUpstreamTimeout`) no enfrían la conexión.
- **Estados con salida de prueba y tope:** `CLOSED → OPEN → HALF_OPEN`.
  - La espera tiene una base que crece de forma exponencial con cada ciclo fallido, con tope (16× la base).
  - Tras la espera pasa una petición de prueba; si va bien, se resetea.
- **Tope duro de saltos por petición** (`MAX_GLOBAL_ATTEMPTS`) y **decir qué modelo respondió**
  (`X-OmniRoute-Model`, `-Fallback-Attempts`).
- **#12954:** si todos los candidatos están excluidos, el error debe decir «reintenta / en enfriamiento»,
  no parecer una configuración rota.
- **No aplica aquí:** cuotas, facturación, multi-cuenta, registros de cientos de breakers con evicción.

## Risks and unknowns

- **Confirmado:** confundir un fallo del endpoint con uno del modelo enfriaría **todos** los modelos a la
  vez ante una caída del backend, porque todos salen por el mismo `BASE_URL` (`server.py:599`).
- **Confirmado:** los tests de 500 existentes seguirían en verde con un respaldo mal hecho, porque el
  doble responde igual a todos los modelos (`tests/backend_mock.py:62-63`). Hacen falta tests que
  distingan por `model`.
- **Confirmado:** en `_chat_chunked`, reintentar solo el trozo k con otro modelo mezcla modelos en una
  misma salida (por ejemplo, una traducción con estilos distintos).
- **Supuesto a validar en el plan:** que un 5xx de llama-swap por falta de memoria al cargar se
  repetiría con un respaldo del grupo `swap`. Por eso el respaldo por defecto apunta al residente.
- **Supuesto a validar en el plan:** el coste del acceso con bloqueo al fichero de enfriamiento en cada
  llamada. Hoy ya hay dos por delegación en `inflight.json`.
