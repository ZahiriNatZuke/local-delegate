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
 "v":"0.11.0","finish_reason":"stop","tokens_in":7163,"tokens_out":230}
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
- `chunks` (solo si > 1): número de llamadas al backend en que se partió la operación (ver
  *Chunking* abajo). Una operación por trozos es **un** evento, no N.
- `error` (solo si `ok=false`), `truncated_in`/`truncated_out`, `raw_len`, `path`, `v`
  (versión del paquete) — todos opcionales; un dashboard viejo o un log legado sin estos
  campos se sigue leyendo sin romperse.

## Cómo se calcula el ahorro

- **Tokens de contexto conservados** = Σ `chars_in` de las llamadas con `source=path`, ÷ 4
  (o la suma de `tokens_in` reales cuando el backend los da). Ese contenido lo leyó el MCP
  en tu máquina y **nunca entró a la ventana de contexto de Claude**: es cuota que no
  gastaste. Las llamadas `inline` **no** cuentan como ahorro (ya viajaron por tu contexto).
- **Tokens generados en local** = Σ `chars_out` ÷ 4: generación que hicieron los modelos
  locales en vez de Claude.
- La aproximación es **~4 chars/token** (`CHARS_PER_TOKEN`) cuando no hay tokens reales.

> Por eso conviene pasar `path` (no `text`) siempre que la fuente sea un archivo: es lo que
> convierte la delegación en ahorro real de cuota.

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

El estado en curso vive en `LOG_DIR/inflight.json` con lock y limpieza de PID: el daemon ve las
llamadas de todas las sesiones que comparten el mismo usuario, incluso durante una migración en la
que todavía convivan clientes HTTP y procesos `stdio`.

## APIs

| Endpoint | Devuelve |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/daemon` | Estado, PID y URLs del daemon HTTP |
| `GET /api/events?from=&to=` | Eventos en el rango (más recientes primero, tope 5000) + `meta` (incluye `files_read`). Sin parámetros: últimos 30 días. `from`/`to` son ISO 8601. |
| `GET /api/stats?from=&to=` | Agregados del mismo rango (por tool, por modelo, por origen del cómputo, totales, tokens ahorrados) |
| `GET /api/inflight` | Delegaciones en curso de todas las sesiones (`elapsed_s`, `backend`, `chunk/chunks`) + `last_event_ts` y `now` para el indicador de actividad |
| `GET /api/backend` | Proxy best-effort de `/running` de llama-swap, modelos con status, y `origin`/`host` del endpoint (`{"available": false}` si no responde) |
| `GET /favicon.svg` | Icono de marca |
