# Savings & metrics

## Qué se mide

El MCP escribe una línea JSONL por llamada. Desde v0.2 el log rota por mes
(`usage-YYYYMM.jsonl`, mes UTC) dentro del directorio de datos del usuario; si fijaste
`LOCAL_DELEGATE_LOG` a un archivo explícito, ese archivo se usa tal cual, sin rotar
(compatibilidad con instalaciones que ya apuntaban a una ruta fija). El `usage.jsonl`
legado de versiones anteriores a la 0.2 no se migra: el dashboard lo sigue leyendo como
fuente adicional.

```json
{"ts":"2026-07-07T21:20:00+00:00","tool":"local_summarize","model":"gemma4-26b-a4b",
 "source":"path","chars_in":28654,"chars_out":919,"latency_ms":502,"ok":true,
 "backend":"remote","backend_host":"pc.tailnet.ts.net:9292",
 "v":"0.13.0","finish_reason":"stop","tokens_in":7163,"tokens_out":230}
```

Cuando responde un **modelo de respaldo**, el evento suma `model_requested` (el que se pidió),
`fallback_reason` (`http_500`, `en enfriamiento`…) y `fallback_class` (`model`, `capacity_or_load`,
`cooldown`); un evento fallido lleva `error_class` (`configuration`, `model`…). Hasta la 0.34.0
esos valores se escribían en español (`modelo`, `capacidad_o_carga`, `enfriamiento`,
`configuracion`…); el panel, `local_status` y los scripts de medición los siguen leyendo y los
cuentan junto a los nuevos. `model` sigue
siendo el que **respondió** y `chunks` cuenta también las llamadas del respaldo, así que los tokens se
atribuyen a quien los gastó y un evento sin salto es idéntico a los de antes. El panel marca esas
filas con **↪** y la tarjeta de delegaciones dice cuántas tuvieron salto: una medición que coincida
con saltos pudo contaminarla un swap.

- `source`: **`path`** = el input se leyó *server-side* (no entró al contexto de Claude) ·
  **`inline`** = el texto ya viajó por tu contexto.
- `chars_in` / `chars_out`: tamaño de entrada procesada / salida generada.
- `chars_out_raw` (desde la 0.36.0): caracteres que generó el modelo **antes** del post-proceso
  (quitar el razonamiento `<think>`, completar las secciones del resumen) y de los avisos; en una
  operación troceada, la suma de todas sus llamadas. Sirve para ver cuánto se perdió entre lo
  generado y lo devuelto. Nunca guarda el texto.
- Parámetros del backend por rol (ver [Configuration](Configuration.md#parámetros-del-backend-por-rol));
  los cuatro campos se omiten cuando no aplican, así que un evento sin parámetros es idéntico a los
  de antes:
  - `backend_params`: `{"role": "<rol>", "values": {<clave>: <valor>}, "source": {<clave>: "env"}}`.
    Solo aparece si la operación llevó alguna clave. `values` lleva cada valor con su tipo JSON, en
    el orden del catálogo, y son los valores **intentados**: el campo sale también si el backend los
    rechazó. `source` solo aparece si alguna clave vino de `LOCAL_DELEGATE_BACKEND_PARAMS`, y lista
    solo esas (las demás son del fichero). `local_delegate` con modelo explícito nunca lo lleva.
  - `reasoning_chars` (solo si es mayor que 0): caracteres de razonamiento de **todas** las llamadas
    de la operación (intentos fallidos, respaldos, trozos y pasos de map/reduce incluidos):
    `reasoning_content` más lo que se quitó entre etiquetas `<think>`. Sale también sin parámetros
    de rol, si el modelo razonó por su cuenta. Nunca guarda el texto del razonamiento. El
    razonamiento que Qwen deja en la respuesta sin etiquetas no se puede contar.
  - `backend_params_rejected: true`: el backend rechazó los parámetros (HTTP 400) y la operación
    siguió sin ellos tras un reintento que funcionó.
  - `reasoning_skipped: "context"`: alguna llamada iba a razonar pero no cabía en el contexto del
    modelo y fue sin razonamiento.

  El panel marca en la lista de delegaciones las filas que razonaron y las que llevaron parámetros
  (con un estado propio si se rechazaron), y el diálogo de la fila da el detalle.
- `tokens_in` / `tokens_out`: tokens reales que reportó el backend (`usage.prompt_tokens` /
  `usage.completion_tokens`), cuando los da. Si faltan, el dashboard estima con `chars/4`.
- `finish_reason`: `choices[0].finish_reason` del backend (p. ej. `"length"` si la salida se
  truncó por `max_tokens` — en ese caso la tool también avisa en el texto devuelto).
- `backend`: dónde corrió la **inferencia** — `local` si el endpoint escucha en loopback,
  `remote` en cualquier otro caso (p. ej. esta Mac usando la GPU de la PC). `backend_host` es
  el `host:puerto` del endpoint, sin esquema ni credenciales. Ojo: describe el **cómputo**, no
  el archivo — el MCP y la lectura de `path` son siempre locales. Los eventos anteriores a la
  v0.11.0 no traen el campo y el dashboard los muestra como `n/d`, nunca como locales.
- `chunks` (solo si > 1): **número de llamadas al backend** en que se partió la operación (ver
  *Chunking* abajo). Ojo con el nombre: son llamadas, no trozos — en el map-reduce el *reduce*
  suma llamadas propias. Una operación por trozos es **un** evento, no N, así que quien agregue
  debe leerlo como `chunks or 1`.
- `pieces` (solo en operaciones troceadas, desde la 0.43.0): **número de trozos** en que se partió
  la entrada. Con `chunks` al lado se distinguen los trozos de las llamadas: `pieces: 3, chunks: 4`
  son tres trozos y una combinación. Los eventos anteriores no lo traen.
- `steps` (solo en operaciones troceadas): cada paso (`kind`: map, reagrupado o reduce) con sus
  `chars_out` y su `finish_reason`, nunca su texto. Desde la 0.43.0 un paso cortado por `length`
  que se reemplazó por su reintento partido lleva `"retried": true` y ya no cuenta como truncado.
- `input_unit` (solo si no es `chars`): qué mide `chars_in`. En `local_describe_image` vale
  `bytes`, porque ahí la entrada es una imagen y **estimar tokens dividiendo bytes entre 4 da un
  número disparatado** (×46 medido contra el token real). Los eventos anteriores a la v0.14.0 no
  lo traen y se reconocen por el nombre de la tool.
- `connection_failure` (solo si la delegación no pudo conectar con el backend): la **causa** del
  fallo, con los mismos nombres que usan el badge del panel y `doctor` (`dns`, `refused`,
  `connect_timeout`, `credential`…; tabla en [Troubleshooting](Troubleshooting.md)). `error` sigue
  valiendo `connect_error`. Hasta la 0.34.0 la clave era `fallo_conexion` y los valores iban en
  español (`rechazada`, `timeout_conexion`…): se siguen leyendo.
- `cancel_reason` (solo con `error: "cancelled"`, desde la 0.41.0): la
  delegación se paró porque quien la pidió dejó de esperarla. `notification` (llegó
  `notifications/cancelled`, como el Esc de Claude Code o el puente de Desktop al cerrarse),
  `disconnect` (el cliente cortó la conexión de la petición) o `aborted` (se cerró la sesión u otra
  cancelación del SDK). Va con `ok: false`, `chars_out: 0` y la latencia hasta la cancelación; el
  modelo y `chars_in` son los de la operación que llegó a empezar.
- `tool_use_id` (solo si el cliente lo manda; Claude Code sí, Codex y los scripts no): el id de la
  llamada en el transcript, leído de `_meta["claudecode/toolUseId"]`. Es la clave exacta para
  cruzar la línea con el transcript.
- `caller_kind` (`main` o `subagent`), `caller_agent_type`, `caller_effort`, `caller_model` y
  `caller_src` (`hook+transcript` o `hook`): **quién pidió** la delegación. Los escribe el servidor
  a partir de la nota que deja el hook `record_call.py` (antes `anotar_llamada.py`; ver
  [Coste equivalente](#coste-equivalente-a-precio-de-api)); sin nota, la línea no lleva ningún
  `caller_*`. Nunca lleva el id de sesión.
- **Espera frente a lentitud** (solo si el backend manda `timings`, como llama-server; si no, se
  omiten, nunca valen 0):
  - `inference_ms`: Σ `prompt_ms` + `predicted_ms` de **todas** las llamadas reales de la operación,
    saltos incluidos.
  - `wait_ms`: `latency_ms − inference_ms` (mínimo 0): todo lo que no fue inferencia medida —turno,
    plaza, cola de llama-swap, carga del modelo— y también una llamada fallida sin `timings` (un
    timeout, un 500), que cuenta entera aquí.
  - `tok_s` y `prefill_tok_s`: velocidad de generación y de lectura del prompt, **solo de las llamadas
    del modelo que respondió** (`model`), a dos decimales.
  - `pace_rel`: `tok_s` / la velocidad normal de ese modelo (la mediana de `tok_s` de sus últimos 50
    eventos correctos con `tokens_out` ≥ 8; hacen falta 10). Sin referencia, o con `tokens_out`
    desconocido, se omite.
  - `slow` va con `pace_rel` en todo evento con referencia: `true` si `pace_rel` <
    `LOCAL_DELEGATE_SLOW_THRESHOLD` (0,5), `false` si no. Con backend **local**, una
    llamada lenta lleva además `free_ram_mb` (la RAM libre en ese momento, best-effort), porque la
    causa más común es que Windows haya echado parte del modelo de la VRAM.
- **Turno del daemon:** `turn_wait_ms` (solo si > 0) es lo que la operación esperó turno; `turn:
  "forced"` marca una concesión forzada por `LOCAL_DELEGATE_TURN_MAX_S`.
- **Afinidad** (ver [Tools](Tools.md#afinidad-usar-el-modelo-que-ya-está-cargado)): `routing:
  "affinity"` cuando respondió un alternativo ya cargado en lugar del modelo del rol, con
  `model_requested` (el del rol), `affinity_foreign_flight` (peticiones de otros clientes en vuelo
  contra ese modelo cuando se decidió) y `affinity_failed: true` si, sin peticiones ajenas, el
  alternativo tardó en empezar como si hubiera que cargarlo (se descargó a pesar del margen). Si el
  alternativo falló y respondió el rol o su cadena, el evento no lleva `routing` y sí
  `affinity_dropped` (el alternativo que se probó) y `affinity_dropped_class` (la clase del fallo).
  **Una fila con `routing: "affinity"` no es un respaldo**: no lleva ↪ ni cuenta en «con salto»,
  aunque tenga `model_requested`.
- `error` (solo si `ok=false`), `truncated_in`/`truncated_out`, `raw_len`, `path`, `v`
  (versión del paquete) — todos opcionales; un dashboard viejo o un log legado sin estos
  campos se sigue leyendo sin romperse.

### Concurrencia: máquina de origen y fases (desde la 0.45)

Para saber quién esperó a quién cuando delegan a la vez la PC y la Mac (cada una con su propio
proceso y su propio log), cada entrada lleva:

- `host`: la máquina que escribió la entrada. Por defecto, el nombre corto del equipo (hasta el
  primer punto); `LOCAL_DELEGATE_MACHINE_NAME` lo fija a mano ([Configuration](Configuration.md)).
  Va en **todas** las entradas, también en las que no llegan al backend. Si la llamada llegó al
  `/mcp` del daemon **desde otra máquina** (por ejemplo, la Mac por la tailnet), `host` es esa
  máquina y no la del daemon, y `host_via` dice de dónde salió: `header` (el cliente mandó
  `X-Local-Delegate-Host`), `forwarded` (un proxy local como `tailscale serve` pasó
  `X-Forwarded-For`) o `ip` (la dirección de quien conectó). Sin `host_via`, la llamada es de la
  propia máquina. Las entradas de `/api/inflight` de una llamada llegada desde otra máquina llevan los
  mismos `host` y `host_via`; una entrada sin `host` es de la propia máquina del daemon.
- `concurrency` (solo en las operaciones que pasaron por el backend), un objeto con:
  - `requested_model`: el modelo que pidió la tool (el del rol o el explícito). `model` sigue siendo
    el que respondió.
  - `phases`: por cada fase que hubo, `{start, end, ms, n}`. `start` es la hora UTC (ISO, con
    milisegundos) del primer paso por la fase, `end` la del último, `ms` la suma de duraciones y `n`
    cuántas veces. Las fases:
    - `turn`: la espera del **turno** del daemon. No aparece si la operación no pidió turno (backend
      remoto, como la Mac, o sin topología).
    - `slot`: la espera de una **plaza** de `LOCAL_DELEGATE_MAX_CONCURRENT_REQUESTS`.
    - `backend`: el POST al backend, de principio a fin. **Incluye la cola de llama-swap y la carga
      del modelo**: lo que el backend tardó en empezar no se distingue aquí de la inferencia; para
      eso están `inference_ms` y `wait_ms`.
  - `backend_models` y `backend_models_at_ms`: lo que `/running` de llama-swap tenía cargado
    (`{modelo: estado}`) **mientras el POST esperaba**: solo se consulta si el envío sigue sin
    respuesta 3 s después de salir (una vez por operación, desde un hilo aparte, con tope de 0,5 s y
    reutilizada 2 s). Una llamada que responde antes no consulta nada: no cargó modelo (las cargas
    medidas tardan 6-14 s) ni esperó a otro, y el daemon no pregunta a llama-swap sin necesidad. Si
    `/running` no responde (otro backend, caído, sin permiso) el campo no aparece.
  - `model_swap`: `true` si en ese momento el modelo del POST no estaba `ready` (llama-swap lo estaba
    cargando, o esperaba a descargar otro para cargarlo). Solo aparece junto a `backend_models`.
  - `inflight_seen`: solo en la PC, cuando el daemon ya miraba la foto `inflight` de llama-swap (la
    afinidad): cada petición en vuelo como `{model, host}`. `host` sale de la cabecera
    `X-Local-Delegate-Host`; `null` si la petición no la traía (otro cliente, o un MCP anterior a la
    0.45). Incluye las propias de este daemon (con su mismo `host`). Máximo 20.

Cada petición de este paquete al backend (`/chat/completions`, `/running`, `/models`…) lleva la
cabecera `X-Local-Delegate-Host` con el mismo nombre. llama-swap la enseña en las cabeceras de cada
petición de su foto `inflight`; de ellas el daemon **solo** lee esa, nunca la credencial.

```json
{"ts":"2026-10-29T18:21:03+00:00","tool":"local_summarize","model":"gemma4-26b-a4b",
 "host":"pc","latency_ms":275900,"ok":false,
 "concurrency":{"requested_model":"gemma4-26b-a4b",
  "phases":{"turn":{"start":"2026-10-29T18:16:27.101+00:00","end":"2026-10-29T18:16:27.102+00:00","ms":1,"n":1},
            "slot":{"start":"2026-10-29T18:16:27.102+00:00","end":"2026-10-29T18:16:27.102+00:00","ms":0,"n":1},
            "backend":{"start":"2026-10-29T18:16:27.160+00:00","end":"2026-10-29T18:21:03.000+00:00","ms":275840,"n":1}},
  "backend_models":{"qwen36-35b-a3b":"ready"},"backend_models_at_ms":3000,"model_swap":true}}
```

**¿Por dónde entra la Mac?** Hay dos caminos y conviven: si su cliente MCP apunta al `/mcp` del
daemon de la PC (entrada `http`), sus llamadas pasan por el turno de la PC y quedan en el log **de
la PC** con `host_via`; si corre su propio MCP en stdio contra `:9292`, quedan en el log **de la
Mac** con su `host` y en la PC solo se ven en la foto `inflight` de llama-swap. Para que una entrada
`http` se reconozca, añade a su entrada la cabecera `"headers": {"X-Local-Delegate-Host": "mac"}`:
detrás de `tailscale serve` el daemon ve todas las conexiones desde `127.0.0.1`, así que sin la
cabecera (y si el proxy no pasa `X-Forwarded-For`) una llamada de la Mac parece local.

**Cruzar los logs de la PC y la Mac.** Copia el `usage-AAAAMM.jsonl` de la Mac junto al de la PC
(cada línea dice su `host`, así que se pueden juntar sin perder el origen) y ordena por
`concurrency.phases.backend.start`. Dos llamadas se pisaron si sus intervalos `backend`
`[start, end]` se solapan; la que tiene `model_swap: true` y empezó mientras la otra tenía
cargado su modelo es la que esperó el cambio. Los relojes de las dos máquinas deben estar en hora
(NTP); un desfase de pocos segundos se nota en el orden pero no cambia qué intervalos se solapan
en esperas de minutos. Las ventanas de `local-delegate test-window` de cada máquina marcan las
pruebas.

## Cómo se calcula el ahorro… y el coste

Son **dos magnitudes distintas**, y confundirlas era el defecto que el panel arrastraba: medía el
ahorro y no medía nada enfrente, así que una delegación resuelta en una llamada y otra que quemó
la GPU dieciséis veces daban el mismo número.

- **Contexto conservado (ahorro)** es un **neto**: lo que no entró a tu contexto (el *bruto*)
  menos lo que la tool te devolvió (el *devuelto*). El bruto es el contenido de entrada de las
  delegaciones con `source=path` que **salieron bien**: lo leyó el MCP en tu máquina y **nunca
  entró a la ventana de contexto de Claude**. Se cuenta **una vez por delegación aunque se
  trocee** — lo que no entró a tu contexto es el documento, no el trabajo de la GPU. Las llamadas
  `inline` **no** cuentan (ya viajaron por tu contexto). La regla completa, en
  [La regla de contabilidad](#la-regla-de-contabilidad).
- **Coste local** = Σ `tokens_in` de **todas** las llamadas al backend. Una delegación troceada
  repite el prompt de sistema en cada trozo, así que aquí sí paga el troceo: en un caso real de
  cuatro trozos, 26 131 tokens de coste frente a 21 044 de ahorro, un **+24 %** que antes no se
  veía en ningún sitio.
- **Generado en local** (el KPI «Generado») = Σ `tokens_out`: generación que hicieron los modelos locales en vez de
  Claude.
- **En el coste local se usa siempre el token real** que reporta el backend (`usage`). La
  aproximación de **~4 chars/token** (`CHARS_PER_TOKEN`) es solo el respaldo del modelo **local**
  cuando el backend no los da, y el dashboard indica cuántos eventos del rango hubo que estimar.
  Los tokens **de Claude** no usan nunca esa cifra: salen de la
  [tabla de densidad](#de-caracteres-a-tokens-de-claude).
- **Delegaciones** frente a **llamadas al backend**: el KPI muestra las dos, y su diferencia es
  exactamente lo que costó trocear.

> Por eso conviene pasar `path` (no `text`) siempre que la fuente sea un archivo: es lo que hace
> que el contenido no entre al contexto de Claude.

### La regla de contabilidad

Hasta la 0.32.0 el KPI sumaba también las delegaciones **fallidas** —una que no pudo conectar
«ahorraba» el documento entero— y no restaba lo que la tool devolvía a tu contexto. Las dos cosas
inflaban el número. Ahora la regla es una sola, escrita igual en Python (`_accounting`) y en el JS
del panel (`acct`), atadas por un test de paridad:

| Concepto | Cuenta | No cuenta |
|---|---|---|
| Bruto | Entrada leída server-side de delegaciones que salieron bien, una vez por delegación; la salida escrita a fichero (`output_to_file`) | Fallos; entrada `inline`; el trabajo extra de trocear |
| Devuelto | Lo que la tool devolvió a Claude en las delegaciones que reclaman ahorro de entrada | El recibo de `output_to_file` (se toma 0); la coletilla de ahorro que se añade después de registrar; el mensaje de error de un fallo |
| Neto | Bruto − devuelto, evento a evento | Las relecturas del mismo fichero (no están en el log) |
| Coste local / Generado | Tokens reportados por el backend, **también en fallos** (la GPU los gastó); la estimación ÷ 4 solo en delegaciones que salieron bien | La estimación sobre el texto de un error |
| Estimados | Delegaciones que salieron bien sin `usage` del backend | Fallos |

- **Qué es un fallo**: el campo `ok` existe y vale exactamente `false`. Un evento con `ok: null` o
  sin la clave **no** es un fallo. Ese mismo predicado es el que usan el KPI «Errores» (la tasa de error), el punto
  rojo de la tabla de actividad y los errores por herramienta de `/api/stats`.
- **El neto puede ser negativo**: una delegación que devuelve más de lo que leyó resta. El KPI, la
  chispa y «Ahorro por herramienta» lo enseñan con su signo (una barra negativa sale a la izquierda
  del 0); no se recorta.
- **El KPI dice los dos números**: «Contexto conservado» enseña el neto y su pista dice
  «bruto X − devuelto Y». Su tooltip avisa de que **no descuenta relecturas**: si Claude vuelve a
  leer el fichero para comprobar el resumen, eso no está en el log.
- **Una imagen sale entera del neto**: ni lo que leyó ni la descripción que devolvió entran en
  «Contexto conservado», así que una imagen no puede dar un neto negativo. El log guarda bytes, no
  dimensiones, y sin dimensiones no hay forma de saber cuántos tokens le costaría a Claude. Las
  imágenes se enseñan en su propio bloque (ver [Imágenes](#imágenes)).

**Desglose en caracteres.** Además de los tokens, cada evento y `/api/stats` llevan lo ahorrado y
lo devuelto **en su unidad de origen**: `chars_saved_text` (texto leído por `path`),
`bytes_saved_image` (la imagen, en bytes), `chars_saved_output` (lo escrito a fichero) y
`chars_returned` (lo devuelto al contexto). Esas cifras son exactas; la conversión a tokens de
Claude es la parte estimada, y pasa por **una sola** función, `claude_tokens` (en JS,
`claudeTokens`), que se explica en la sección siguiente.

**Un ejemplo con cifras reales** (septiembre de 2026 en la máquina de referencia: 143
delegaciones, 7 de ellas fallidas). La columna `÷ 4` es la conversión de antes; la de la derecha,
la de ahora, por densidad:

| Cifra | Con `÷ 4` | Por densidad |
|---|---|---|
| Bruto con la regla de antes (fallos dentro) | 983 871 tokens | — |
| Bruto sin fallos | 873 270 tokens | 1 718 328 tokens |
| Devuelto (289 554 caracteres) | 72 342 tokens | 128 776 tokens |
| **Neto (lo que enseña el KPI)** | **800 928 tokens** | **1 589 552 tokens** |
| Texto ahorrado | 3 463 739 caracteres | igual |
| Imagen ahorrada | 1 489 047 bytes (5 imágenes) | igual, en su bloque |
| Salida a fichero | 5 237 caracteres (3 delegaciones) | igual |

Las cuentas se hacen al **leer** el log, así que los meses pasados se recalculan solos. Sacar los
fallos los hizo **bajar** (agosto, con 2 fallos en 18 delegaciones, pasó de 261 048 a 178 756
tokens de bruto con `÷ 4`, un −32 %); contar en tokens de Claude de verdad los hace **subir**
(septiembre, ×1,98), porque un token de Claude cubre bastante menos de 4 caracteres.

### De caracteres a tokens de Claude

Cuántos caracteres caben en un token depende del **tokenizador** y del **tipo de contenido**. El
paquete trae una tabla de densidad (`resources/data/density.json`), en caracteres por token,
medida el 2026-10-06 con llamadas reales a Claude Code (`claude -p`) sobre textos públicos de este
repo: la entrada que reporta `usage`, menos la de una llamada de control vacía, entre los
caracteres del texto:

| Familia | Columna | prosa | código | log | estructurado | diff |
|---|---|---:|---:|---:|---:|---:|
| nueva | sin numerar | 2,23 | 2,41 | 1,92 | 1,88 | 2,22 |
| nueva | formato `Read` | 2,00 | 2,03 | — | — | — |
| anterior | sin numerar | 3,01 | 3,12 | 2,41 | 2,22 | 2,90 |

«—» es «sin medir». La familia de cada modelo la dice la tabla de precios: **nueva** es el
tokenizador de Claude 4.7 en adelante, medido con Opus 5.5, Sonnet 5.5, Opus 5 y Fable 5.1 (que
dan el mismo número de tokens en cada texto medido); **anterior**, el de los modelos previos,
medido con Haiku 4.5. La columna
**formato `Read`** cuenta la numeración de líneas que añade `Read`: es lo que Claude habría leído
si no hubiera delegado.

Para cada delegación, la regla es una sola y vive en Python (`cost.resolve_density`):

- **familia**: la del modelo que pidió la delegación (`caller_model`); sin modelo, la del
  [respaldo](#cobertura-y-respaldo); un modelo que no está en la tabla de precios se trata como
  familia nueva (`new`) y lleva la marca `assumed_family` (familia supuesta). Un modelo con familia conocida pero
  que no está entre los medidos lleva la marca `family_density` (densidad de la familia);
- **clase de contenido**, sin leer el texto: primero por la tool (`local_lint_summary` → log,
  `local_commit_msg` → diff, `local_explain_code` → código) y si no por la extensión del `path`
  (`.md .txt .rst .html` → prosa; `.py .js .ts .ps1 .sh …` → código; `.json .jsonl .yaml .toml
  .lock .csv .xml .ini` → estructurado; `.log` → log; `.diff .patch` → diff; lo demás, `other`);
- **columna**: formato `Read` si la entrada fue por `path`, sin numerar si no. Lo devuelto a
  Claude va siempre sin numerar (estructurado en `local_extract`, código en `local_boilerplate`,
  prosa en el resto);
- **respaldo de celda**, en este orden: la celda exacta (`measured`); la misma clase sin numerar
  (`unnumbered`); la mayor densidad sin numerar de la familia (`conservative`). Los dos respaldos
  dan **menos** tokens que la celda real, nunca más, porque la numeración solo añade tokens.

`/api/events` entrega cada fila ya resuelta, con `density` (`{"text": [c100, origen],
"returned": …, "output": …}`, en centésimas), `family` y `marks`; Python y el JS del panel
solo dividen (`cantidad × 100 // c100`), así que las dos cuentas no pueden separarse. La coletilla
de ahorro, el recibo de la salida a fichero y `tokens_aprox` de `local_extract` dicen
«≈ N tokens de Claude» con esa misma conversión; la coletilla de `local_describe_image`, solo los
bytes.

### Por qué las cuentas viven en el servidor

`/api/stats` es la **única** implementación de la contabilidad; el panel pide los KPIs ahí en vez
de sumar en el navegador. Solo las series por día se calculan en el cliente, porque agrupar por
«tu día natural» depende de tu zona horaria y el servidor no la conoce; esa copia en JS está atada
a la de Python por un test de paridad que las ejecuta con `node` y compara.

## Coste equivalente a precio de API

La tarjeta del panel enseña la **cota baja** ($X, con la pista «no es un ahorro: tarifa plana») y la
**estimación** (~$Y) como cifras, junto a la tabla por modelo, hilo y esfuerzo de las delegaciones
del rango elegido. Su botón **ⓘ** abre el diálogo con el titular **«Equivalente estimado a precio
de API: entre $X y ~$Y»** y la nota **«no es dinero que hayas ahorrado: tu suscripción es de
tarifa plana»**. La pregunta que responde es otra:
*¿cuánto costaría, a precio de lista de la API, que Claude hubiera leído él mismo lo que se
delegó?* Sirve para comparar el peso de lo delegado entre periodos y entre modelos, no para hacer
cuentas de dinero.

Es una **estimación con supuestos**, y el panel los enseña siempre junto a la cifra, en ese
diálogo de información (cobertura, modelo supuesto, relecturas, densidad, lo que queda fuera,
contrafactual y fecha de precios); sin ese bloque no hay cifra.

### La fórmula

Por cada delegación atribuible:

- **`T`**: sus tokens de Claude netos de texto, `claude_tokens(chars_saved_text, "text") −
  claude_tokens(chars_returned, "returned")`. Puede ser negativo: lo devuelto también entró en
  caché, y resta.
- **Cota baja** = `T × P_w(m, hilo)`: una sola escritura en caché, al precio del modelo `m` que la
  pidió. `P_w` es la escritura a 5 min en un subagente y a 1 h en el hilo principal, que es como
  escribe Claude Code en cada caso (medido en todos los transcripts).
- **Estimación** = `T × (P_w × (1 + cad) + (N − cad) × P_r(m))`: además de escribirlo, ese
  contenido se habría vuelto a leer de la caché en cada una de las `N` peticiones siguientes del
  mismo hilo, y cada caducidad de la caché (`cad`) lo habría reescrito.

El periodo suma los eventos. **El contrafactual** es «si Claude hubiera leído el fichero entero
una vez con `Read`»: por eso la densidad usa la columna con numeración de líneas. El rótulo de la
cota dice **«cota baja con estos supuestos»**: bajo ellos lo es; si Claude hubiera releído el
fichero, no. **No descuenta las relecturas del mismo fichero** (medidas entre ~3 % y ~30 %), que
no están en el log.

Quedan **fuera de la base**, contadas aparte con su número a la vista: las delegaciones que
fallaron, las imágenes (ver [Imágenes](#imágenes)) y la salida escrita a fichero, cuyo
contrafactual es salida generada y no lectura.

### Cobertura y respaldo

Para saber qué modelo pidió cada delegación hacen falta dos piezas:

- **al momento**: el hook `record_call.py` (antes `anotar_llamada.py`; `PreToolUse` sobre `mcp__local-delegate__.*`, se
  instala siempre) deja una nota con el `tool_use_id`, el agente, su tipo, el esfuerzo y el
  transcript. Al escribir la línea del log, el servidor busca la nota y saca el modelo de la cola
  (256 KB) del transcript que señala, sin guardar nada más de él;
- **por relleno**: lo que no se pudo atribuir al momento (el histórico, o una nota que llegó
  tarde) lo atribuye después [`local-delegate recompute-cost`](#local-delegate-recompute-cost),
  cruzando el log con los transcripts: por `tool_use_id` si lo hay, y si no por tool y hora, con
  el `path` como único desempate. Con los datos de referencia, el 96,5 % de las líneas casan sin
  ambigüedad.

La **barra de cobertura** reparte cada delegación en un tramo, en este orden: excluidas (`excluded`: clientes
que no son Claude, como `codex-mcp-client`, y pruebas: el cliente `mcp` de los scripts y las
sesiones de bancos), al momento (`at_call`), por relleno (`backfilled`), pendientes (`pending`: sin
modelo, pero su transcript aún puede existir) y supuestas (`assumed`: el resto). Las excluidas no
suman. Las pendientes y las supuestas se
valoran con el **respaldo** declarado, **Opus 5.5 en subagente** (el grupo más frecuente medido),
y el rótulo lo nombra («3 de 152 con modelo supuesto: Opus 5.5 en subagente»). Se cambia con
`LOCAL_DELEGATE_COST_FALLBACK` (ver [Configuration](Configuration.md#coste-equivalente)).
**Sin la barra no hay cifra.**

El **esfuerzo** se guarda y se enseña, pero no entra en la fórmula: medido, no cambia los tokens
de entrada. Puede cambiar `N`, y por eso el desglose agrupa también por esfuerzo.

### De dónde sale `N`

`N` son las peticiones del mismo hilo posteriores a la delegación, contadas una vez por mensaje,
sin las sintéticas y hasta la primera compactación; una **caducidad** es un hueco mayor que el TTL
de la caché del hilo (300 s en un subagente, 3 600 s en el principal). Por evento, en un solo
orden:

1. el `N` y las caducidades medidos por el relleno en su transcript;
2. si no hay, la mediana de `N` de su grupo (modelo, hilo) en los agregados del último relleno,
   si el grupo tiene al menos 10 casos;
3. si no, el `N` declarado de su hilo: **127 en el principal y 40 en subagente**, medidos con los
   datos de referencia.

No hay variable de entorno para `N`. El panel dice cuántos eventos usan cada origen.

### Lo que enseña el bloque

Junto a la cifra, siempre: la barra de cobertura con el respaldo, el origen de `N`, la densidad por
familia y su origen (con cuántos eventos llevan `densidad de la familia` o `familia supuesta`),
«neto de la respuesta de la tool», la fecha de la tabla de precios, el contrafactual y la frase de
las relecturas. Debajo, un **desglose por modelo, hilo y esfuerzo** con casos, `T`, cota baja y
estimación: ahí se ve que el grupo pesa mucho más que cualquier supuesto, porque el hilo principal
tiene un `N` tres veces mayor y Opus 5 cuesta más que Opus 5.5.

Una delegación cuyo modelo no está en la tabla de precios no suma dólares: se cuenta aparte
(«k delegaciones de modelos sin precio, fuera de la suma»). **Cuando no hay cifra se dice el
motivo, nunca $0**: sin tabla de precios cargable, sin delegaciones en el periodo, o con todas sin
precio.

**Cifra de referencia.** En la máquina de referencia, del 6 de septiembre al 6 de octubre de 2026:
`T` = 1,84 millones de tokens netos (con `÷ 4` serían 0,91), **cota baja $11,50 y estimación
$92,69**, de los que $62,20 son de Opus 5 en el hilo principal (14 casos) y $30,49 de Opus 5.5 en
subagente (135). El panel y el script de la investigación (`atribucion_n.py`) dan lo mismo al
céntimo sobre la misma ventana.

### La tabla de precios

Viaja en el paquete (`resources/data/prices.json`): precio de entrada, salida, escritura de caché
a 5 min y a 1 h, lectura de caché y familia de tokenizador de cada modelo, con la `source` (la
página oficial) y `consulted` (la fecha del último cambio). Se busca por id exacto, quitando antes
la fecha y el sufijo `[1m]`. **Ni la carga de la tabla ni `/api/stats` usan la red**: la tabla la
mantiene al día el [vigilante semanal](Repo-hardening.md#vigilante-de-precios-y-límites), que
abre un PR cuando cambia la página.

Lo que delata una tabla desfasada **en tu máquina** es el **cotejo**: `recompute-cost` recalcula
con la tabla el coste de las sesiones de tus transcripts y lo compara con el que calcula Claude
Code. Si no cuadra, `doctor` lo dice (check `config.cost`, ver
[Troubleshooting](Troubleshooting.md#doctor-da-warn-coste-y-relleno)). En la máquina de referencia
cuadran las 144 filas juzgadas.

## Cuota

El bloque de cuota responde a «¿qué parte de una ventana de 5 h, o de la semanal, supone lo que
delegué?». Para eso hace falta saber cuántos dólares a precio de lista caben en una ventana, y eso
**no se publica**: se calibra. Por eso el bloque tiene un estado por tipo de ventana, y por defecto
es **«sin calibrar»**.

- **Puntos del statusline.** De un registro que escribe tu statusline de Claude Code,
  `~/.claude/quota-statusline.jsonl` o, con el nombre de siempre, `~/.claude/cuota-statusline.jsonl`
  (si existen los dos, se leen los dos; una fila por refresco con `ts`, `session_id`, `model`,
  `five_hour`, `five_reset`, `seven_day`, `seven_reset`, `cost_usd` y, opcional, `effort`):
  local-delegate **no lo instala**, solo lo lee si existe. De cada ventana sale como mucho un punto:
  cuánto subió el % (Δ%), con las dos filas de una misma sesión porque las sesiones en paralelo
  ven el % desfasado, y cuánto costó a precio de lista lo que hicieron todas las sesiones del
  registro en ese intervalo (Δ$, de los incrementos de `cost_usd`).
  Su capacidad es `C = Δ$ × 100 / Δ%`. Se descartan, y se cuentan por motivo, los puntos con
  Δ% < 10 (`small_delta`), sin uso local (`no_local_use`), con sesiones que gastaban cuota sin
  estar en el registro, como `claude -p` (`contaminated`), los que se solapan con otro
  (`overlapping`), las filas con un % imposible (`out_of_range`) y los de más de 60 días
  (`expired`). El panel los dice en palabras.
- **Puntos de rechazo.** Cada rechazo de cuota que aparece en los transcripts da un punto con
  Δ% = 100. Solo sirven de **comprobación**: recogen una parte del coste en sesiones grandes, un
  sesgo del orden del propio umbral, así que no entran en el cálculo.
- **Criterio, escrito antes de mirar.** Un tipo pasa a **calibrado** si, con los puntos del
  statusline vigentes, quedan **al menos 3** y su dispersión (la mediana de cuánto se aleja cada
  uno de la mediana de los demás) es **menor del 25 %**. Si los dos puntos más recientes se alejan
  más del 25 % en el mismo sentido, es **deriva** (cambiaron los límites): los anteriores dejan de
  contar.
- **Sin calibrar**, la tarjeta de cuota **no se pinta**; el diálogo de información (el botón
  **ⓘ** de la tarjeta de coste) enseña los puntos que hay, los rechazos, la dispersión si hay dos o
  más, los descartes por motivo y **qué falta** («faltan 3 puntos del statusline»). **Ningún %.**
- **Calibrado**, la tarjeta enseña por cada ventana la cifra «A – B %» y un medidor de 0 a
  100 % (A en sólido, de A a B en claro); el diálogo dice «≈ entre A % y B % de una ventana de 5 h», con A y B la cota baja y la
  estimación de lo delegado en las últimas 5 h (o 7 días) entre la capacidad, sea cual sea el
  periodo que elijas en el panel. Si la capacidad calibrada sale menor que la de un rechazo
  observado, avisa de un probable uso en otras superficies.
- **Reinicio a mano.** Cuando el vigilante avisa de que cambió el artículo de límites de uso,
  `local-delegate recompute-cost --reset-calibration five_hour` (o `seven_day`) deja fuera
  los puntos anteriores de ese tipo.

Todo punto del statusline lleva la marca `low_bound_if_other_surfaces` (cota baja si hubo uso en
otras superficies): claude.ai, otra máquina o
Claude Desktop gastan la misma cuota y desde aquí no se ven. En la máquina de referencia, el
2026-10-06, los dos tipos siguen **sin calibrar** (faltan 3 puntos del statusline: los que había
salieron contaminados o fuera de rango).

## Imágenes

Las delegaciones de `local_describe_image` se enseñan en su propia tarjeta, como cifras: número de
imágenes, bytes leídos en local (Σ `bytes_saved_image`) y caracteres devueltos a Claude. Sin
imágenes en el rango la tarjeta no se pinta; la explicación va en el diálogo de información. **Sin ninguna
cifra de tokens de Claude**: el log guarda bytes, no dimensiones, y sin dimensiones no hay forma
honesta de calcularla. Por lo mismo, no entran ni en «Contexto conservado» ni en el coste
equivalente.

## `local-delegate recompute-cost`

El daemon y el panel **no leen** `~/.claude/projects` ni el registro del statusline (con una sola
excepción acotada: la cola del transcript que señala la nota del hook, para sacar el modelo de una
línea). Lo que necesita el coste y la cuota lo calcula este comando, que lanzas tú:

```bash
local-delegate recompute-cost
local-delegate recompute-cost --reset-calibration five_hour   # o seven_day
```

Lee en local los transcripts, el registro del statusline y el log de uso, y escribe **solo** en el
directorio de logs (`LOG_DIR`):

- `attribution-AAAAMM.json` (antes `atribucion-AAAAMM.json`), por mes: para cada línea del log, el
  modelo, el hilo, el esfuerzo, `N`, las caducidades (`expiries`), cómo se cruzó (`match`: `exact`,
  `window`, `window+path`, `ambiguous`, `no_match`) y si venía de una sesión de pruebas (`bench`).
  Una entrada solo se sustituye por otra de cruce mejor. Si de un mes solo existe el fichero viejo,
  se lee traducido y la primera escritura siembra el nuevo desde él, una sola vez; el viejo no se
  toca nunca;
- `cost-aggregates.json` (antes `coste-agregados.json`): el cotejo de la tabla de precios
  (`check`), los agregados de `N` por grupo (`n_by_month`), los puntos de calibración (`points`)
  con sus descartes (`discards`) y los reinicios (`resets`). Si solo existe el viejo, se lee
  traducido y la primera corrida siembra el nuevo desde él, una sola vez; el viejo no se toca.

**Ni texto de conversaciones, ni rutas, ni ids de sesión, ni prompts**: solo números, fechas, ids
de modelo, niveles de esfuerzo y nombres de motivo (y, como clave del relleno, el `tool_use_id` o
la hora y la tool de la línea, que ya están en el log). Es idempotente y **no escribe nada en
`~/.claude`**. Los puntos de calibración se funden con los anteriores, así que un punto cuyo
transcript ya se borró sigue contando hasta que caduque. En la máquina de referencia tarda 3,3 s
sobre 456 transcripts.

**Cuándo lanzarlo.** Claude Code borra los transcripts a los `cleanupPeriodDays` de
`~/.claude/settings.json` (30 días si no está puesto), y con ellos la posibilidad de atribuir las
delegaciones que no se atribuyeron al momento. `doctor` da `warn` cuando la delegación pendiente
más antigua tiene más de ese plazo **menos 10 días**: es el aviso para lanzarlo. Sin los JSON del
comando, el panel valora todo con el respaldo y el `N` declarado, y el bloque de cuota dice que no
hay datos y cómo generarlos.

## Pruebas y ventanas de prueba

Una prueba en vivo contra el MCP o el daemon escribe en el mismo log que el trabajo real. El log
**no se reescribe**: todo el que lo lee aparta las pruebas con **una sola regla**
(`attribution.test_reason`). Una fila es una prueba si:

1. la pidió el cliente `mcp` (el de los scripts del repo);
2. es de un banco (el relleno de `recompute-cost` la marcó `banco`); o
3. su `ts` cae en una **ventana de prueba** de `LOG_DIR/test-windows.json`.

Esa regla la aplican el panel entero, `local_status`, el coste equivalente (que ya apartaba las dos
primeras), `recompute-cost` (los agregados de `N`) y los medidores de `scripts/`. Las delegaciones
de Codex **siguen contando** como uso; solo el coste las deja fuera («no es Claude»).

### Marcar una prueba en vivo

```bash
local-delegate test-window start --label "ola 11, paso 5"   # imprime el id: guárdalo
# … la prueba …
local-delegate test-window stop w-20261008T012005Z
```

**Guarda el id que imprime `start` y cierra con `stop <id>`.** Puede haber varias ventanas abiertas
a la vez (agentes en paralelo), y entonces `stop` sin id sale con código 2 y lista los ids abiertos.
Para una prueba ya pasada, `local-delegate test-window add INICIO FIN --label "…"` (ISO 8601, sin
zona = UTC; repetirla no duplica). `local-delegate test-window list` (o `--json`) dice cuántas filas
del log caen en cada ventana.

Una marca está dentro de una ventana si `inicio <= ts <= fin` comparando instantes **truncados al
segundo**: el log escribe `ts` al segundo, así que una fila de las `01:22:31` está dentro de una
ventana que acaba a las `01:22:31.544` y una de las `01:22:32` no. Una ventana abierta llega hasta
el momento de leer. Si dos ventanas se solapan, la fila cuenta una vez, para la que empieza antes.

**Cada máquina marca en su `LOG_DIR`.** La Mac delega contra el backend de la PC pero con su propio
daemon y su propio log: sus pruebas se marcan con el CLI de la Mac. Las ventanas no se sincronizan.

`doctor` avisa (`metrics.test_windows`) si el fichero es ilegible, si hay entradas ignoradas o si una
ventana lleva abierta más de 12 h, con la orden para cerrarla. `local_status` dice cuántas filas de
prueba quedaron fuera del mes y qué ventanas siguen abiertas.

### El interruptor «Pruebas»

En la barra del panel, junto al rango. **Apagado** (por defecto) el panel aparta las pruebas de los
KPIs, las tablas, los gráficos, las imágenes y la tarjeta de hooks; **encendido**, las tres
peticiones del panel llevan `include_tests=1` y las enseñan. El estado se recuerda en el navegador.
Su ⓘ dice cuántas filas quedaron fuera en el rango y nombra las ventanas abiertas; si hay alguna,
el botón lleva un punto. El **coste equivalente y la cuota no dependen del interruptor**: los dos
ven siempre todas las filas y apartan las pruebas ellos mismos. Lo vivo (el indicador EN CURSO / EN
VIVO y `/api/inflight`) tampoco se filtra.

### Los medidores

```bash
uv run python scripts/measure_adoption.py --since 2026-09-12 --json
uv run python scripts/measure_cooldown.py --since 2026-09-15T19:26:41
```

Los dos leen el `LOG_DIR` de `config` (el mismo `test-windows.json` que el panel) y aplican las
ventanas solos; `--include-tests` las desactiva. `measure_cooldown.py` aplica además los tramos de
`--exclude` (con la misma regla de instantes), y su salida dice cuánto quitó cada fuente.
`measure_adoption.py` aparta también, en el log de uso, las filas del cliente `mcp`.

## Delegaciones del mod y adopción del plugin

Desde la 0.40, el mod del [plugin de Claude Code](Claude-plugin.md) puede pedir delegaciones él
mismo (los comandos `/local-summarize`, `/local-commit` y `/local-lint`). Esas filas llevan un
`tool_use_id` que empieza por `toolu_plugin_` y **no** las decidió el modelo:

- Siguen dentro del total y de cada KPI; no se apartan como las pruebas.
- `/api/stats` las cuenta en `mod_calls`, en el total y en cada cliente de `by_client`. El panel
  lo dice en «Quién delegó», junto a cada cliente («N del mod»).

Para saber si el plugin hace que **el modelo** delegue más, la medición está fijada de antemano
(REQ-024 del SDD `claude-plugin-and-mods`):

```bash
uv run python scripts/measure_plugin_adoption.py                                  # solo la base
uv run python scripts/measure_plugin_adoption.py --install 2026-10-22T20:00:00Z   # base y 14 días después
```

- **Qué mide**: el % de sesiones interactivas de Claude Code (`cli` y la pestaña Code de Claude
  Desktop) con al menos una delegación decidida por el modelo. Cruza el `tool_use_id` del log de
  uso con el transcript principal de cada sesión en `~/.claude/projects`.
- **Qué no cuenta**: las llamadas del mod, las pruebas (la regla común y las ventanas de
  `test-window`), los subagentes y las sesiones `-p` o del SDK.
- **Periodos**: la base va del 2026-10-08 (antes faltan los `tool_use_id`) hasta `--install`, el
  instante en que se instaló la 0.40.0; el después, los 14 días siguientes.
- **Criterio**: éxito si el después tiene al menos 30 sesiones y sube al menos 10 puntos sobre la
  base. El JSON lo da en `criterion.status`: `no_install`, `too_early`, `too_few_sessions`, `met`
  o `not_met`.

Solo lee el `LOG_DIR` y los transcripts, e imprime cifras: no escribe nada ni saca su contenido.

## La web

Dashboard en `http://127.0.0.1:9393`. Con `local-delegate serve` vive en el daemon singleton;
el modo `stdio` conserva la web embebida por compatibilidad. KPIs, serie
temporal de ahorro, barras por herramienta/modelo, donut `path` vs `inline`, feed de
actividad, y un selector de **rango** (Hoy / 7 días / 30 días / mes anterior / todo el
histórico / personalizado) que decide qué llama al backend, no solo un filtro visual: solo
se abren y parsean los archivos `usage-YYYYMM.jsonl` cuyo mes interseca el rango pedido
(más el legado, siempre candidato). El pie de página muestra cuántos archivos se leyeron.
Filtros de tool/modelo siguen siendo client-side dentro del rango cargado. El panel enseña además
los bloques de [coste equivalente](#coste-equivalente-a-precio-de-api), [cuota](#cuota) e
[imágenes](#imágenes), cada uno escondido si `/api/stats` no trae su clave. Solo **lee** los
JSONL; no interfiere con el MCP ni el backend (salvo el proxy de estado de `/api/backend`,
una lectura sin efectos).

Las seis tarjetas de KPIs tienen **tamaño fijo**: no cambian de ancho ni de alto con las cifras. Sus
bordes casan con los dos paneles de arriba (las tres primeras bajo el de modelos y rendimiento, las
tres últimas bajo el de GPU y procesos); entre 880 y 1320 px van tres bajo cada panel y, más
estrecho, se apilan. Una cifra que no cabe se muestra con fuente más pequeña o en forma corta
(«45,7 mil M tok») y el valor exacto queda al pasar el ratón; lo mismo con las cifras de coste,
cuota e imágenes. Si un título no cabe con la fuente de reserva del sistema, los seis se aprietan
por igual antes de recortarse con «…» (desde la 0.36.1).

### Idioma

El panel sale en **español o en inglés**, por visitante: el selector `ES`/`EN` de la cabecera
cambia todo el panel sin recargar ni perder el rango o los filtros, y la elección se guarda en el
navegador (`localStorage`, clave `ld-lang`), no en el servidor. Sin elección guardada, el panel
sigue al idioma del **navegador**: español si empieza por `es`, inglés en cualquier otro caso. El
idioma del daemon no influye: el mismo daemon sirve a la vez a un visitante en español y a otro en
inglés. Los textos del panel salen del catálogo `panel.*` (`resources/i18n/<idioma>/panel.json`),
que el servidor inyecta con los dos idiomas; lo que el servidor redacta (causas del backend,
motivos de la cuota y del coste, roles del catálogo de modelos y el resumen de cada tool) lo pide
el panel con `?lang=` en cada `/api/*`. Los números y las fechas siguen el idioma: `8.003` y `1,5`
en español, `8,003` y `1.5` en inglés. La prosa ya escrita en el log (el motivo de un respaldo,
la etiqueta de una ventana de prueba) se enseña tal cual, en el idioma en que se escribió.

La fila **Procesos del backend** de la tarjeta Sistema solo cuenta el `llama-swap` que escucha
en el puerto de `LOCAL_DELEGATE_BASE_URL`: los que lanza la suite de tests (el mismo ejecutable en
un puerto libre) no aparecen.

### Zona horaria

El log se escribe en **UTC** (un instante sin ambigüedad y comparable entre máquinas), pero el
dashboard presenta todo en **tu zona horaria**: "Hoy" empieza a tu medianoche, las barras del
gráfico agrupan por tu día natural, el rango personalizado interpreta las fechas como locales y
la tabla muestra tu hora. El pie de página indica qué zona y offset se aplicaron. Al servidor
siempre se le mandan instantes absolutos (`from`/`to` con offset), así que no necesita conocer
tu zona.

### Local vs remoto

La insignia del panel de backend («cómputo local» o «remoto») y la columna **Cómputo** de la
tabla (con «Local», «Remoto» o «Sin dato») separan lo generado por el backend de esta máquina de lo
generado por uno remoto. El origen se deduce de la dirección del backend en el momento de la
llamada (loopback = local) y se fuerza con `LOCAL_DELEGATE_BACKEND_ORIGIN` detrás de un túnel. Las
delegaciones que otra máquina hace contra este backend se apuntan en el log de esa máquina. El
panel ya no trae el donut *Dónde corrió el cómputo*: el backend es fijo por instalación y el donut
siempre daba 100 % de un lado.

### Delegaciones en curso ("En curso")

Tarjeta con polling cada 2 s (solo si la pestaña está visible; al volver a la pestaña refresca
de inmediato) que muestra las delegaciones en vuelo ahora mismo —tool, modelo, segundos
transcurridos, si el cómputo es local o remoto y el progreso `trozo i/N` en operaciones por
chunks— y el modelo montado en llama-swap si el backend expone `/running`. Cuando nada corre, el
título pasa a **«Última delegación»** y enseña la última terminada; vuelve a «En curso» en cuanto
hay una llamada viva.

Desde la 0.43.0 el chip de progreso dice la **fase** de una operación troceada: `trozo i/N`
mientras se procesan los trozos, **«Combinando N trozos…»** durante la combinación (reduce o
reagrupado) y **«Reintentando trozo i/N»** cuando un trozo cortado o que no cabía se vuelve a
partir. `/api/inflight` lo expone como `phase` (`reduce` o `retry`; sin el campo, los trozos).

Desde la 0.45.0 (issue #477) cada entrada de `/api/inflight` lleva `state`: **`running`** (tiene
plaza y está en el backend, o entre dos trozos de una operación que ya llegó), **`retrying`**
(reintentando un trozo cortado) o **`queued`** (espera turno o plaza, o aún no llegó al backend;
con espera de turno, `queue_position` es su puesto). Sale de la espera y la plaza reales, no del
texto de la fase. Con `state`, «En curso» separa **«Procesando (n)»** y **«En cola (m)»**: las de
la cola llevan un círculo discontinuo en vez del giro, van atenuadas y, con turno, su puesto
(`#3`). Un daemon anterior no manda `state` y el panel pinta la lista única de siempre.

En la tabla de actividad, una operación troceada lleva un chip con sus trozos y las llamadas de
más: **`3 +1`** son tres trozos y una combinación, con el título «3 trozos · 4 llamadas al
backend»; `3×` son tres trozos sin llamadas extra. El diálogo de la fila da las dos cifras
(«Trozos» y «Llamadas al backend»). Los eventos anteriores a la 0.43.0, sin `pieces`, se ven como
antes (`4×`, que son llamadas).

`/api/inflight` y `/api/backend` se piden **por separado**, como mucho una petición de cada uno en
vuelo, y el siguiente sondeo sale 2 s **después de que termine** el anterior. Así un backend lento
(una VPN que no contesta) no congela «En curso» ni apila peticiones.

### Estado del backend y de los modelos

**El badge** del panel de backend dice la causa, no solo «caído». Tiene cuatro aspectos:

| Aspecto | Cuándo |
|---|---|
| Verde, «conectado» | El sondeo respondió con la lista de modelos. El `title` es la URL base |
| Ámbar, la etiqueta sola («sin acceso», «responde con error», «respuesta no válida», «no responde a tiempo») | Hay alguien contestando, pero no sirve: credencial rechazada, error HTTP, cuerpo que no se entiende o lectura agotada |
| Rojo, «caído · etiqueta» («caído · no resuelve», «caído · nadie escucha»…) | No se llega al backend: DNS, conexión rechazada, sin ruta, sin respuesta a la conexión, URL no válida, fallo de red |
| Neutro, «comprobando…» | El panel acaba de abrirse y el primer sondeo falló: todavía no hay un estado que enseñar |

El `title` del badge es el detalle de la causa (la tabla completa de causas y qué hacer con cada
una está en [Troubleshooting](Troubleshooting.md)). Las etiquetas y los detalles los redacta
**solo** `failures.py`, en el daemon; el panel los recibe ya escritos (campos `cause`, `label` y
`detail` de `/api/backend`).

**Hacen falta dos sondeos fallidos seguidos para pasar a «caído».** Un fallo suelto tras uno bueno
**conserva** lo que se pintaba —badge en verde, filas con su último estado y sin atenuar— y el
`title` del badge añade «último sondeo: …». El segundo fallo seguido pinta la causa y solo
entonces las filas pasan a «desconocido», atenuadas. Un sondeo bueno lo devuelve a «conectado» al
instante, y al reconectar el panel pide de nuevo el estado y las métricas del backend sin esperar
al ciclo de 60 s. `local_status` y `doctor` **no** tienen esta espera: hacen una sola consulta y
dicen lo que ven.

**La lista de modelos no cambia con la conexión.** El daemon guarda la última lista buena de cada
`BASE_URL`; si el backend deja de responder, sigue sirviendo esa lista (con `models_stale: true`),
así que salen las mismas filas en el mismo orden: primero por el rol del catálogo que las usa
(mecánico, largo, código, visión) y después las que no tienen rol, por id.

**El texto de cada fila** sale de esta tabla, en orden (gana la primera):

| Texto | Cuándo |
|---|---|
| esperando al backend | El backend no está disponible y hay una llamada a ese modelo en vuelo |
| desconocido | El backend no está disponible |
| en cola local | Todas las llamadas a ese modelo esperan **dentro de local-delegate**, antes de enviarse: plaza en el máximo de llamadas a la vez (`slot`) o turno del daemon, porque su modelo choca con el que está en uso (`turn`) |
| en curso | El backend no es llama-swap (no expone `/running`) y hay una llamada en vuelo |
| montado / frío | El backend no es llama-swap: según el `status` de `/v1/models` |
| cargando | llama-swap lo está arrancando |
| procesando | Montado y con una llamada en vuelo |
| montado | Montado, sin llamadas |
| esperando turno | Hay una llamada ya enviada a llama-swap, pero el modelo no está listo en `/running` (otro ocupa la GPU o se está descargando) |
| descargando | llama-swap lo está parando |
| frío | El resto |

La espera local se publica en la entrada en vuelo con el campo `local_wait` (el motivo como
texto: `slot` o `turn`) y se borra al terminar. Así «esperando turno» queda solo para lo que ya se envió a
llama-swap: el panel no le atribuye una espera nuestra. Un motivo nuevo que el panel no conozca se
enseña tal cual en el `title` de la fila. Con `turn`, la entrada lleva además `turn_in_use` (los
modelos que tienen el turno) y `turn_position` (su puesto en la cola), y el `title` de la fila y
«En curso» dicen «esperando turno del daemon (en uso: <modelos>)».

En la tabla de actividad, cada llamada cuyo backend manda `timings` enseña bajo la latencia
«espera X s · inferencia Y s» (`wait_ms` e `inference_ms`), y una llamada lenta lleva la marca
**«lento ×0,37»** (`pace_rel`), con su velocidad en el `title`. Una fila con `routing: "affinity"`
no lleva ↪: la afinidad no es un respaldo.

La tarjeta de **métricas de llama-swap** dice «sin datos (… requiere llama-swap ≥ v236)» **solo**
cuando el backend responde 404 a `/api/metrics/stats`; con cualquier otro fallo dice «sin datos:
etiqueta» (por ejemplo «sin datos: no resuelve»).

El indicador de la cabecera tiene tres estados y **no** depende del rango elegido ni del
auto-refresco: `EN CURSO` (hay delegaciones vivas), `EN VIVO` (última actividad hace menos de
30 min) y `EN REPOSO`. Se repinta cada segundo, porque pasar a reposo es una transición por
paso del tiempo, no por llegada de datos, y descuenta el desfase entre el reloj del navegador y
el del servidor.

### Chunking de documentos largos

`local_translate` y `local_delegate` parten las entradas largas por límites naturales (headers
Markdown → párrafos → líneas → corte duro) en trozos de `LOCAL_DELEGATE_CHUNK_CHARS` y hacen una
llamada por trozo con `max_tokens <= LOCAL_DELEGATE_CHUNK_MAX_TOKENS`. Las salidas se concatenan
en orden reponiendo el separador original de cada trozo, así que las costuras conservan el
formato. Si un trozo aun así vuelve truncado, se vuelve a partir y se reintenta. El evento del
log lleva `chunks: N` (llamadas) y, desde la 0.43.0, `pieces` (trozos), con la latencia y los
tokens sumados de toda la operación.

### Map-reduce en las tools de reducción

El chunking de arriba sirve para **transformar** —traducir, reescribir, reformatear—: cada trozo
se corresponde con su parte del resultado, así que concatenar las salidas es correcto. Para
**reducir** a un único resultado (un resumen global) concatenar no vale: daría un resumen por
trozo pegado con otro, no un resumen del conjunto.

Por eso `local_summarize` y `local_lint_summary` hacen **map-reduce** cuando la entrada no cabe
en el modelo: resumen cada parte (*map*) y luego resumen los resúmenes (*reduce*). Si los
parciales tampoco caben, el reduce se repite por niveles, con un tope de tres. Como en el
chunking, la operación deja **un** evento de log con `chunks: N`.

Desde la 0.43.0 el map/reduce trata los parciales cortados igual que el chunking: si un paso del
map o del reagrupado sale por `length`, se descarta, se parte el trozo (o el grupo) y se reintenta,
hasta dos niveles. Antes el parcial cortado entraba tal cual en la combinación. Si aun así queda
alguno cortado, el aviso nombra el trozo y sus líneas, y en `steps` el paso reemplazado lleva
`"retried": true`.

Hasta la 0.12.0 estas tools simplemente **truncaban** la entrada y avisaban: de un log de CI de
200 000 caracteres se resumía el principio y el resto se descartaba, que es justo donde suelen
estar los errores que importan. Ahora se lee entero.

`local_extract` truncaba a propósito hasta la 0.35: fusionar los objetos JSON de varios trozos no
tiene una respuesta única (¿se queda el primer valor?, ¿se concatenan?, ¿qué pasa si se
contradicen?). Desde la 0.36.0 lo decide el modelo en un paso final con schema, con los parciales
delante; si solo un parcial trae datos, ese es el resultado sin llamada extra. `local_explain_code`
también deja de truncar: map-reduce por definiciones de primer nivel.

El estado en curso vive en `LOG_DIR/inflight.json` con lock y limpieza de PID: el daemon ve las
llamadas de todas las sesiones que comparten el mismo usuario, incluso durante una migración en la
que todavía convivan clientes HTTP y procesos `stdio`.

## APIs

| Endpoint | Devuelve |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/daemon` | Estado, PID y URLs del daemon HTTP |
| `GET /api/events?from=&to=&include_tests=` | Eventos en el rango (más recientes primero, tope 5000) + `meta` (incluye `files_read`, `excluded_tests` y `tests_in_range`). Sin `include_tests=1`, sin las pruebas. Sin parámetros: últimos 30 días. `from`/`to` son ISO 8601. Cada fila llega **fundida** con el relleno de `recompute-cost` (o el respaldo) y con su `density`, `family` y `marks` resueltas (y `caller_origin`: `line`, `backfill` o `fallback`): el JS no funde ni resuelve nada |
| `GET /api/stats?from=&to=&include_tests=&session=` | Agregados del mismo conjunto que `/api/events` (`excluded_tests`, `tests_in_range` y `open_test_windows` dicen qué se apartó y qué ventanas siguen abiertas) (por tool, por modelo, por origen del cómputo, por cliente, totales): `tokens_context_saved` (el **bruto**, ya sin fallos), `tokens_returned`, `tokens_context_net` (el **neto** del KPI), el desglose `chars_saved_text`, `bytes_saved_image`, `chars_saved_output` y `chars_returned`, `tokens_local_input`, `tokens_generated_local`, `backend_calls` y `estimated_events`. `by_tool`, `by_backend` y `by_client` llevan `tokens_net` junto a `tokens_saved`. Además: `cost` (la cifra o el motivo de que no la haya —`figure` y `reason`—, la barra de cobertura `bar`, el respaldo `fallback`, el origen de `N` `n_origin`, la densidad usada `density`, los modelos sin precio `unpriced`, lo que queda fuera de la base `outside_base`, el desglose `breakdown` y la fecha de la tabla `table`), `quota` (estado por tipo de ventana, `five_hour` y `seven_day`, con `status` `calibrated` o `uncalibrated`, `reason`, `points`, `rejection_points`, `discards`, `drift`, `reset`, `median_C`, `warning`, `a_pct`, `b_pct` y `pct_reason`; y `has_aggregates` y `command`), `images` (`n`, `bytes`, `chars_returned`), `density_table` y `mod_calls` (las llamadas que pidió el mod del plugin, también por cliente en `by_client`; ver [Delegaciones del mod](#delegaciones-del-mod-y-adopción-del-plugin)). Los tokens son de Claude, por densidad. Con `session=<id de sesión de Claude Code>` solo cuenta las delegaciones de esa sesión (lo usa la barra de estado del mod): la línea del log no guarda el id, sino su clave de un solo sentido `caller_session_key` (sha256 truncado), y el daemon calcula la misma clave del id que recibe; las líneas sin clave (anteriores a la 0.41, o de clientes sin el hook `record-call`) no cuentan. **No** aplica el tope de 5000 de `/api/events`: alimenta los KPIs del panel |
| `GET /api/inflight` | Delegaciones en curso de todas las sesiones (`elapsed_s`, `backend`, `chunk/chunks` y, si la llamada espera dentro de local-delegate, `local_wait` con el motivo: `slot` o `turn`; con `turn`, también `turn_in_use` y `turn_position`; desde la 0.45.0, `state` = `running`, `retrying` o `queued`, y `queue_position` en una espera de turno) + `last_event_ts` y `now` para el indicador de actividad. Con `?session=<id>` (la banda del mod) cada entrada lleva además `mine` y la respuesta `mine_count`: solo son de esa sesión las que ella lanzó (se compara la clave de un solo sentido, nunca el id); sin parámetro, la respuesta es la de siempre |
| `GET /api/backend` | Sondeo del backend: `available`, `models` (con `status`; si no responde, la última lista buena de esa URL con `models_stale: true`), `running` y `running_ok` (si `/running` respondió; solo se pide cuando `/models` respondió), `causa`, `etiqueta` y `detalle` (los tres `null` si está conectado), y `origin`/`host` del endpoint |
| `GET /api/status` | Versión, catálogo de modelos y tools, y un bloque `backend` con `available`, `models`, `models_stale`, `causa`, `etiqueta`, `detalle`, `origin` y `host` |
| `GET /api/backend/stats` | Métricas de llama-swap (`/api/metrics/stats`). Sin datos trae `causa`, `etiqueta`, `detalle` y `status_http` |
| `GET /api/llamaswap/status`, `POST /api/llamaswap/watch`, `GET /api/llamaswap/watch/<id>` | Estado de llama-swap para el CLI y `doctor`, y vigía de recarga de `llamaswap residency`. Ver [Daemon](Daemon.md#llama-swap-visto-desde-el-daemon) |
| `GET /api/system` | RAM, VRAM y procesos del backend, más `platform`, `origin`, `host` y `panel_url` (panel de la máquina del backend; vacío si es local) |
| `GET /api/hooks?from=&to=&include_tests=` | Lo que los hooks consultivos **sugirieron** en el rango, sin los eventos que caen en una ventana de prueba salvo con `include_tests=1` (`excluded_tests` dice cuántos): `total`, `suggested`, `rate`, y desglose por evento, categoría y día. `enabled: false` cuando `LD_HOOK_TELEMETRY_LOG` no está definida |
| `?lang=es\|en` | Lo aceptan `/api/stats`, `/api/hooks`, `/api/backend`, `/api/backend/stats` y `/api/status`: los textos que redacta el servidor (`reason`, `warning`, `pct_reason`, la etiqueta y el detalle de la causa, los roles y el resumen de cada tool) salen en ese idioma. Sin él, o con otro valor, en el del proceso del daemon |
| `GET /favicon.svg` | Icono de marca — el **mismo** fichero que la landing y que el icono del header del panel, inyectado desde `resources/brand/favicon.svg` |

### Sugerencias de los hooks

Los hooks consultivos escriben su propia telemetría —opt-in, activada con `LD_HOOK_TELEMETRY_LOG`,
y **sin prompts, comandos ni rutas**: evento, categoría, tamaños, la sesión, la versión del script,
el estado del bloqueo y, en las lecturas, una huella de la ruta en vez de la ruta—. Ese registro existía desde
hacía tiempo y el dashboard no lo miraba.

La tarjeta cuenta **cuántas veces un hook sugirió delegar**, en el mismo rango que el resto de la
página. Y hay una frontera que conviene tener clara, porque es la única forma de que el número
signifique algo:

> **La tarjeta no mide cuántas sugerencias se siguieron.** El hook sugiere y tú decides.

Esa advertencia la abre el botón **ⓘ** de la cabecera de la tarjeta. Las categorías y los motivos
se enseñan con etiquetas en español («Lectura», «Shell», «Lectura acotada», «Pequeño», «Por otro
MCP»…); en el log y en `/api/hooks` siguen siendo las claves internas (`read`, `bounded`, `small`,
`foreign_mcp`…). Los valores que escribían los hooks hasta la versión anterior (`acotada`,
`pequeno`, `mcp_ajeno`…) se leen igual y se pintan con la misma etiqueta.

Durante mucho tiempo eso no se podía medir de ninguna forma: eran dos registros sin identificador
común, y cruzarlos habría sido inventar una correlación y presentarla como un dato. **Ya no.** Cada
aviso y cada bloqueo llevan un identificador; cuando el hook rechaza una lectura deja una nota con
ese identificador y una **huella** de la ruta —nunca la ruta—, y la tool que recibe ese mismo
`path` se queda con él en su evento (`block_id`; `bloqueo_id` hasta la 0.34.0). El identificador no viaja por el agente a
propósito: pedirle que lo pase sería depender de que obedezca, que es justo lo que se quiere medir.

Quien responde la pregunta es `scripts/measure_adoption.py`, que cruza los dos registros sin trabajo
manual:

```bash
python scripts/measure_adoption.py --since 2026-09-12
```

Da el denominador por motivo y por camino, los bloqueos, cuántos acabaron en una delegación
correlacionada, y cuántas delegaciones fueron espontáneas —esas no se las puede apuntar la regla—.
Avisa además si la ventana mezcla dos versiones de script, porque una sesión abierta hereda el
entorno del lanzador y entonces la muestra junta dos políticas sin decirlo.

Desde la 0.36.0 parte además los recuentos en dos **tramos** («antes» y «después», campo
`by_side` de `--json`), y la frontera es la **versión**, no la fecha: un evento de hook es del
tramo «después» si la huella del script que lo escribió está en `scripts/data/hook_hashes_after.json`,
y una fila del log de uso si su `v` es igual o posterior a `package_version_after`
(`scripts/data/measurement_boundaries.json`). Así, los eventos de una máquina que se quedó en una
versión anterior siguen en «antes» aunque se escriban después.

Lo que sí responde es «¿cuánta de mi actividad pasa por delante del hook, y en qué parte cree que
hay una oportunidad?». En la máquina de referencia, con 1817 eventos en tres días: **17,0 % de
sugerencias**, repartidas de forma muy desigual — `bash` acumulaba 1396 eventos con **cero**
sugerencias, mientras `lint` iba 283 de 283. Ese desglose por categoría es más informativo que el
total.

**La tarjeta se esconde si no hay telemetría activada**, en vez de enseñar ceros: un panel a cero
se leería como «los hooks no sugieren nada», que es una conclusión falsa sacada de un fichero que
ni siquiera existe.
