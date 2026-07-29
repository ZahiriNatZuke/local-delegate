# Savings & metrics

## Qué se mide

El MCP escribe una línea JSONL por llamada. Desde v0.2 el log rota por mes
(`usage-YYYYMM.jsonl`, mes UTC) dentro del directorio de datos del usuario; si fijaste
`LOCAL_DELEGATE_LOG` a un archivo explícito, ese archivo se usa tal cual, sin rotar
(compatibilidad con instalaciones que ya apuntaban a una ruta fija). El `usage.jsonl`
legado de versiones anteriores a la 0.2 no se migra: el dashboard lo sigue leyendo como
fuente adicional.

```json
{"ts":"2026-07-07T21:20:00+00:00","tool":"local_summarize","model":"llama31-8b",
 "source":"path","chars_in":28654,"chars_out":919,"latency_ms":502,"ok":true,
 "backend":"remote","backend_host":"pc.tailnet.ts.net:9292",
 "v":"0.13.0","finish_reason":"stop","tokens_in":7163,"tokens_out":230}
```

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
- `error` (solo si `ok=false`), `truncated_in`/`truncated_out`, `raw_len`, `path`, `v`
  (versión del paquete) — todos opcionales; un dashboard viejo o un log legado sin estos
  campos se sigue leyendo sin romperse.

## Cómo se calcula el ahorro… y el coste

Son **dos magnitudes distintas**, y confundirlas era el defecto que el panel arrastraba: medía el
ahorro y no medía nada enfrente, así que una delegación resuelta en una llamada y otra que quemó
la GPU dieciséis veces daban el mismo número.

- **Contexto conservado (ahorro)** = el contenido de entrada de las llamadas con `source=path`.
  Lo leyó el MCP en tu máquina y **nunca entró a la ventana de contexto de Claude**: es cuota que
  no gastaste. Se cuenta **una vez por delegación aunque se trocee** — lo que no entró a tu
  contexto es el documento, no el trabajo de la GPU. Las llamadas `inline` **no** cuentan (ya
  viajaron por tu contexto).
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
chunks— y el modelo montado en llama-swap si el backend expone `/running`.

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
| `GET /api/stats?from=&to=` | Agregados del mismo rango (por tool, por modelo, por origen del cómputo, totales): `tokens_context_saved`, `tokens_local_input`, `tokens_generated_local`, `backend_calls` y `estimated_events`. **No** aplica el tope de 5000 de `/api/events`: alimenta los KPIs del panel |
| `GET /api/inflight` | Delegaciones en curso de todas las sesiones (`elapsed_s`, `backend`, `chunk/chunks`) + `last_event_ts` y `now` para el indicador de actividad |
| `GET /api/backend` | Proxy best-effort de `/running` de llama-swap, modelos con status, y `origin`/`host` del endpoint (`{"available": false}` si no responde) |
| `GET /favicon.svg` | Icono de marca |
