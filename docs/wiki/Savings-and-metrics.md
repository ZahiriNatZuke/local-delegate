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
 "v":"0.2.0","finish_reason":"stop","tokens_in":7163,"tokens_out":230}
```

- `source`: **`path`** = el input se leyó *server-side* (no entró al contexto de Claude) ·
  **`inline`** = el texto ya viajó por tu contexto.
- `chars_in` / `chars_out`: tamaño de entrada procesada / salida generada.
- `tokens_in` / `tokens_out`: tokens reales que reportó el backend (`usage.prompt_tokens` /
  `usage.completion_tokens`), cuando los da. Si faltan, el dashboard estima con `chars/4`.
- `finish_reason`: `choices[0].finish_reason` del backend (p. ej. `"length"` si la salida se
  truncó por `max_tokens` — en ese caso la tool también avisa en el texto devuelto).
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

### Delegaciones en curso ("En curso")

Tarjeta con polling cada 2 s (solo si la pestaña está visible) que muestra las
delegaciones que están en vuelo ahora mismo (tool, modelo, segundos transcurridos) y el
modelo montado en llama-swap si el backend expone `/running`.

El estado en curso vive en `LOG_DIR/inflight.json` con lock y limpieza de PID: el daemon ve las
llamadas de todas las sesiones que comparten el mismo usuario, incluso durante una migración en la
que todavía convivan clientes HTTP y procesos `stdio`.

## APIs

| Endpoint | Devuelve |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/daemon` | Estado, PID y URLs del daemon HTTP |
| `GET /api/events?from=&to=` | Eventos en el rango (más recientes primero, tope 5000) + `meta` (incluye `files_read`). Sin parámetros: últimos 30 días. `from`/`to` son ISO 8601. |
| `GET /api/stats?from=&to=` | Agregados del mismo rango (por tool, por modelo, totales, tokens ahorrados) |
| `GET /api/inflight` | Delegaciones en curso en este proceso, con `elapsed_s` |
| `GET /api/backend` | Proxy best-effort de `/running` de llama-swap (`{"available": false}` si no responde) |
| `GET /favicon.svg` | Icono de marca |
