# Savings & metrics

## Qué se mide

El MCP escribe una línea JSONL por llamada en `usage.jsonl`:

```json
{"ts":"2026-07-07T21:20:00+00:00","tool":"local_summarize","model":"llama31-8b",
 "source":"path","chars_in":28654,"chars_out":919,"latency_ms":502,"ok":true}
```

- `source`: **`path`** = el input se leyó *server-side* (no entró al contexto de Claude) ·
  **`inline`** = el texto ya viajó por tu contexto.
- `chars_in` / `chars_out`: tamaño de entrada procesada / salida generada.

## Cómo se calcula el ahorro

- **Tokens de contexto conservados** = Σ `chars_in` de las llamadas con `source=path`, ÷ 4.
  Ese contenido lo leyó el MCP en tu máquina y **nunca entró a la ventana de contexto de Claude**:
  es cuota que no gastaste. Las llamadas `inline` **no** cuentan como ahorro (ya viajaron por tu
  contexto).
- **Tokens generados en local** = Σ `chars_out` ÷ 4: generación que hicieron los modelos locales
  en vez de Claude.
- La aproximación es **~4 chars/token** (`CHARS_PER_TOKEN`).

> Por eso conviene pasar `path` (no `text`) siempre que la fuente sea un archivo: es lo que
> convierte la delegación en ahorro real de cuota.

## La web

Dashboard en `http://127.0.0.1:9393` (embebido en el MCP, hilo daemon). KPIs, serie temporal de
ahorro, barras por herramienta/modelo, donut `path` vs `inline`, y feed de actividad. Filtros por
tool/modelo/rango y auto-refresco. Solo **lee** el JSONL; no interfiere con el MCP ni el backend.

## APIs

| Endpoint | Devuelve |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/events` | Eventos crudos (más recientes primero, tope 5000) + `meta` |
| `GET /api/stats` | Agregados (por tool, por modelo, totales, tokens ahorrados) |
| `GET /favicon.svg` | Icono de marca |
