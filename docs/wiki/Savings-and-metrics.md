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
`fallback_reason` (`http_500`, `en enfriamiento`…) y `fallback_class` (`modelo`, `capacidad_o_carga`,
`enfriamiento`); un evento fallido lleva `error_class` (`configuracion`, `modelo`…). `model` sigue
siendo el que **respondió** y `chunks` cuenta también las llamadas del respaldo, así que los tokens se
atribuyen a quien los gastó y un evento sin salto es idéntico a los de antes. El panel marca esas
filas con **↪** y la tarjeta de delegaciones dice cuántas tuvieron salto: una medición que coincida
con saltos pudo contaminarla un swap.

- `source`: **`path`** = el input se leyó *server-side* (no entró al contexto de Claude) ·
  **`inline`** = el texto ya viajó por tu contexto.
- `chars_in` / `chars_out`: tamaño de entrada procesada / salida generada.
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
- `input_unit` (solo si no es `chars`): qué mide `chars_in`. En `local_describe_image` vale
  `bytes`, porque ahí la entrada es una imagen y **estimar tokens dividiendo bytes entre 4 da un
  número disparatado** (×46 medido contra el token real). Los eventos anteriores a la v0.14.0 no
  lo traen y se reconocen por el nombre de la tool.
- `fallo_conexion` (solo si la delegación no pudo conectar con el backend): la **causa** del
  fallo, con los mismos nombres que usan el badge del panel y `doctor` (`dns`, `rechazada`,
  `timeout_conexion`, `credencial`…; tabla en [Troubleshooting](Troubleshooting.md)). `error` sigue
  valiendo `connect_error` y `error_class` no cambia, así que un lector viejo del log no se rompe.
- `error` (solo si `ok=false`), `truncated_in`/`truncated_out`, `raw_len`, `path`, `v`
  (versión del paquete) — todos opcionales; un dashboard viejo o un log legado sin estos
  campos se sigue leyendo sin romperse.

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
- **Generado en local** = Σ `tokens_out`: generación que hicieron los modelos locales en vez de
  Claude.
- **Se usa siempre el token real** que reporta el backend (`usage`). La aproximación de
  **~4 chars/token** (`CHARS_PER_TOKEN`) es solo el respaldo para cuando el backend no los da, y
  el dashboard indica cuántos eventos del rango hubo que estimar.
- **Delegaciones** frente a **llamadas al backend**: el KPI muestra las dos, y su diferencia es
  exactamente lo que costó trocear.

> Por eso conviene pasar `path` (no `text`) siempre que la fuente sea un archivo: es lo que
> convierte la delegación en ahorro real de cuota.

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
  sin la clave **no** es un fallo. Ese mismo predicado es el que usan «Tasa de error», el punto
  rojo de la tabla de actividad y los errores por herramienta de `/api/stats`.
- **El neto puede ser negativo**: una delegación que devuelve más de lo que leyó resta. El KPI, la
  chispa y «Ahorro por herramienta» lo enseñan con su signo (una barra negativa sale a la izquierda
  del 0); no se recorta.
- **El KPI dice los dos números**: «Contexto conservado» enseña el neto y su pista dice
  «bruto X − devuelto Y». Su tooltip avisa de que **no descuenta relecturas**: si Claude vuelve a
  leer el fichero para comprobar el resumen, eso no está en el log.
- **Una imagen por `path`** cuenta como bruto el token real de entrada que reportó el modelo local
  (`chars_in` de `local_describe_image` son **bytes**), y como devuelto la descripción. Sin
  `tokens_in` reportado no reclama nada.

**Desglose en caracteres.** Además de los tokens, cada evento y `/api/stats` llevan lo ahorrado y
lo devuelto **en su unidad de origen**: `chars_saved_text` (texto leído por `path`),
`bytes_saved_image` (la imagen, en bytes), `chars_saved_output` (lo escrito a fichero) y
`chars_returned` (lo devuelto al contexto). La conversión a tokens de Claude pasa por **una sola**
función, `tokens_claude` (en JS, `tokensClaude`). Hoy divide los caracteres entre 4, que es una
cifra intermedia: la sustituirá una conversión que tenga en cuenta el tipo de contenido.

**Un ejemplo con cifras reales** (septiembre de 2026 en la máquina de referencia: 143
delegaciones, 7 de ellas fallidas):

| Cifra | Valor |
|---|---|
| Bruto con la regla de antes (fallos dentro) | 983 871 tokens |
| Bruto sin fallos | 873 270 tokens (−11 %) |
| Devuelto | 72 342 tokens (289 554 caracteres) |
| **Neto (lo que enseña el KPI)** | **800 928 tokens** |
| Texto ahorrado | 3 463 739 caracteres |
| Imagen ahorrada | 1 489 047 bytes (5 imágenes) |
| Salida a fichero | 5 237 caracteres (3 delegaciones) |

Las cuentas se hacen al **leer** el log, así que los meses pasados se recalculan solos y **bajan**:
agosto, con 2 fallos en 18 delegaciones, pasa de 261 048 a 178 756 tokens de bruto (−32 %).

### Por qué las cuentas viven en el servidor

`/api/stats` es la **única** implementación de la contabilidad; el panel pide los KPIs ahí en vez
de sumar en el navegador. Solo las series por día se calculan en el cliente, porque agrupar por
«tu día natural» depende de tu zona horaria y el servidor no la conoce; esa copia en JS está atada
a la de Python por un test de paridad que las ejecuta con `node` y compara.

## La web

Dashboard en `http://127.0.0.1:9393`. Con `local-delegate serve` vive en el daemon singleton;
el modo `stdio` conserva la web embebida por compatibilidad. KPIs, serie
temporal de ahorro, barras por herramienta/modelo, donut `path` vs `inline`, feed de
actividad, y un selector de **rango** (Hoy / 7 días / 30 días / mes anterior / todo el
histórico / personalizado) que decide qué llama al backend, no solo un filtro visual: solo
se abren y parsean los archivos `usage-YYYYMM.jsonl` cuyo mes interseca el rango pedido
(más el legado, siempre candidato). El pie de página muestra cuántos archivos se leyeron.
Filtros de tool/modelo siguen siendo client-side dentro del rango cargado. Solo **lee** los
JSONL; no interfiere con el MCP ni el backend (salvo el proxy de estado de `/api/backend`,
una lectura sin efectos).

### Zona horaria

El log se escribe en **UTC** (un instante sin ambigüedad y comparable entre máquinas), pero el
dashboard presenta todo en **tu zona horaria**: "Hoy" empieza a tu medianoche, las barras del
gráfico agrupan por tu día natural, el rango personalizado interpreta las fechas como locales y
la tabla muestra tu hora. El pie de página indica qué zona y offset se aplicaron. Al servidor
siempre se le mandan instantes absolutos (`from`/`to` con offset), así que no necesita conocer
tu zona.

### Local vs remoto

El donut *Dónde corrió el cómputo*, la insignia del panel de backend y la columna **Cómputo** de
la tabla separan lo generado por el backend de esta máquina de lo generado por uno remoto. Útil
cuando alternas topologías: la misma Mac puede tener sesiones contra su propio backend y sesiones
apuntando a la GPU de la PC.

### Delegaciones en curso ("En curso")

Tarjeta con polling cada 2 s (solo si la pestaña está visible; al volver a la pestaña refresca
de inmediato) que muestra las delegaciones en vuelo ahora mismo —tool, modelo, segundos
transcurridos, si el cómputo es local o remoto y el progreso `trozo i/N` en operaciones por
chunks— y el modelo montado en llama-swap si el backend expone `/running`. Cuando nada corre, el
título pasa a **«Última delegación»** y enseña la última terminada; vuelve a «En curso» en cuanto
hay una llamada viva.

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
**solo** `fallos.py`, en el daemon; el panel los recibe ya escritos.

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
| en cola local | Todas las llamadas a ese modelo esperan **dentro de local-delegate**, antes de enviarse (hoy, plaza en el máximo de llamadas a la vez) |
| en curso | El backend no es llama-swap (no expone `/running`) y hay una llamada en vuelo |
| montado / frío | El backend no es llama-swap: según el `status` de `/v1/models` |
| cargando | llama-swap lo está arrancando |
| procesando | Montado y con una llamada en vuelo |
| montado | Montado, sin llamadas |
| esperando turno | Hay una llamada ya enviada a llama-swap, pero el modelo no está listo en `/running` (otro ocupa la GPU o se está descargando) |
| descargando | llama-swap lo está parando |
| frío | El resto |

La espera local se publica en la entrada en vuelo con el campo `espera_local` (el motivo como
texto) y se borra al terminar. Así «esperando turno» queda solo para lo que ya se envió a
llama-swap: el panel no le atribuye una espera nuestra. Un motivo nuevo que el panel no conozca se
enseña tal cual en el `title` de la fila.

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
log lleva `chunks: N` con la latencia y los tokens sumados de toda la operación.

### Map-reduce en las tools de reducción

El chunking de arriba sirve para **transformar** —traducir, reescribir, reformatear—: cada trozo
se corresponde con su parte del resultado, así que concatenar las salidas es correcto. Para
**reducir** a un único resultado (un resumen global) concatenar no vale: daría un resumen por
trozo pegado con otro, no un resumen del conjunto.

Por eso `local_summarize` y `local_lint_summary` hacen **map-reduce** cuando la entrada no cabe
en el modelo: resumen cada parte (*map*) y luego resumen los resúmenes (*reduce*). Si los
parciales tampoco caben, el reduce se repite por niveles, con un tope de tres. Como en el
chunking, la operación deja **un** evento de log con `chunks: N`.

Hasta la 0.12.0 estas tools simplemente **truncaban** la entrada y avisaban: de un log de CI de
200 000 caracteres se resumía el principio y el resto se descartaba, que es justo donde suelen
estar los errores que importan. Ahora se lee entero.

`local_extract` sigue truncando a propósito: fusionar los objetos JSON de varios trozos no tiene
una respuesta única (¿se queda el primer valor?, ¿se concatenan?, ¿qué pasa si se contradicen?) y
adivinarla sería peor que avisar.

El estado en curso vive en `LOG_DIR/inflight.json` con lock y limpieza de PID: el daemon ve las
llamadas de todas las sesiones que comparten el mismo usuario, incluso durante una migración en la
que todavía convivan clientes HTTP y procesos `stdio`.

## APIs

| Endpoint | Devuelve |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/daemon` | Estado, PID y URLs del daemon HTTP |
| `GET /api/events?from=&to=` | Eventos en el rango (más recientes primero, tope 5000) + `meta` (incluye `files_read`). Sin parámetros: últimos 30 días. `from`/`to` son ISO 8601. |
| `GET /api/stats?from=&to=` | Agregados del mismo rango (por tool, por modelo, por origen del cómputo, por cliente, totales): `tokens_context_saved` (el **bruto**, ya sin fallos), `tokens_returned`, `tokens_context_net` (el **neto** del KPI), el desglose `chars_saved_text`, `bytes_saved_image`, `chars_saved_output` y `chars_returned`, `tokens_local_input`, `tokens_generated_local`, `backend_calls` y `estimated_events`. `by_tool`, `by_backend` y `by_client` llevan `tokens_net` junto a `tokens_saved`. **No** aplica el tope de 5000 de `/api/events`: alimenta los KPIs del panel |
| `GET /api/inflight` | Delegaciones en curso de todas las sesiones (`elapsed_s`, `backend`, `chunk/chunks` y, si la llamada espera dentro de local-delegate, `espera_local` con el motivo) + `last_event_ts` y `now` para el indicador de actividad |
| `GET /api/backend` | Sondeo del backend: `available`, `models` (con `status`; si no responde, la última lista buena de esa URL con `models_stale: true`), `running` y `running_ok` (si `/running` respondió; solo se pide cuando `/models` respondió), `causa`, `etiqueta` y `detalle` (los tres `null` si está conectado), y `origin`/`host` del endpoint |
| `GET /api/status` | Versión, catálogo de modelos y tools, y un bloque `backend` con `available`, `models`, `models_stale`, `causa`, `etiqueta`, `detalle`, `origin` y `host` |
| `GET /api/backend/stats` | Métricas de llama-swap (`/api/metrics/stats`). Sin datos trae `causa`, `etiqueta`, `detalle` y `status_http` |
| `GET /api/system` | RAM, VRAM y procesos del backend, más `platform`, `origin` y `host` |
| `GET /api/hooks?from=&to=` | Lo que los hooks consultivos **sugirieron** en el rango: `total`, `suggested`, `rate`, y desglose por evento, categoría y día. `enabled: false` cuando `LD_HOOK_TELEMETRY_LOG` no está definida |
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

Durante mucho tiempo eso no se podía medir de ninguna forma: eran dos registros sin identificador
común, y cruzarlos habría sido inventar una correlación y presentarla como un dato. **Ya no.** Cada
aviso y cada bloqueo llevan un identificador; cuando el hook rechaza una lectura deja una nota con
ese identificador y una **huella** de la ruta —nunca la ruta—, y la tool que recibe ese mismo
`path` se queda con él en su evento (`bloqueo_id`). El identificador no viaja por el agente a
propósito: pedirle que lo pase sería depender de que obedezca, que es justo lo que se quiere medir.

Quien responde la pregunta es `scripts/medir_adopcion.py`, que cruza los dos registros sin trabajo
manual:

```bash
python scripts/medir_adopcion.py --desde 2026-09-12
```

Da el denominador por motivo y por camino, los bloqueos, cuántos acabaron en una delegación
correlacionada, y cuántas delegaciones fueron espontáneas —esas no se las puede apuntar la regla—.
Avisa además si la ventana mezcla dos versiones de script, porque una sesión abierta hereda el
entorno del lanzador y entonces la muestra junta dos políticas sin decirlo.

Lo que sí responde es «¿cuánta de mi actividad pasa por delante del hook, y en qué parte cree que
hay una oportunidad?». En la máquina de referencia, con 1817 eventos en tres días: **17,0 % de
sugerencias**, repartidas de forma muy desigual — `bash` acumulaba 1396 eventos con **cero**
sugerencias, mientras `lint` iba 283 de 283. Ese desglose por categoría es más informativo que el
total.

**La tarjeta se esconde si no hay telemetría activada**, en vez de enseñar ceros: un panel a cero
se leería como «los hooks no sugieren nada», que es una conclusión falsa sacada de un fichero que
ni siquiera existe.
