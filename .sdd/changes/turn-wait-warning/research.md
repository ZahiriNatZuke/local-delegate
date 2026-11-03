# Investigación del issue #537 — `local_summarize` lenta bajo concurrencia

Fuente: log de uso real `usage-202611.jsonl` (solo lectura), entradas del 2026-11-02 entre 14:05Z y 14:50Z.
No hay log propio del daemon (no existe fichero; el daemon no escribe eventos de operaciones remotas).

## La llamada del issue
Entrada `ts=2026-11-02T14:30:03Z`, `local_summarize`, `path`, `chars_in=28987`, modelo `gemma4-26b-a4b` (rol largo), un solo trozo (`chunks` vacío), `tokens_in=8701`, `tokens_out=1056`, `ok=true`.

| Tramo | Tiempo | % |
|---|---|---|
| Espera del turno común (`turn_wait_ms`) | 291,6 s | 85 % |
| Plaza (`slot`) | 0 s | 0 % |
| Backend total (fase `backend`) | 50,9 s | 15 % |
| — de eso, carga del modelo (`model_swap=true`, `gemma4` en `starting`) | ≈13 s | |
| — de eso, inferencia (`inference_ms`) | 37,9 s | |
| **Total (`latency_ms`)** | **342,8 s** | |

Llegó a las 14:24:20, obtuvo el turno a las 14:29:12, terminó a las 14:30:03.

## Qué tenía delante (orden de llegada)
Ráfaga de 14 llamadas entre 14:24:16 y 14:24:30 de dos sesiones (una con 4 subagentes y otra sin clave de sesión), mezclando dos modelos que no caben juntos: `gemma4-26b-a4b` (summarize) y `qwen36-35b-a3b` (explain_code / commit_msg).

| Llega | Envía | Termina | Tool | Modelo | Nota |
|---|---|---|---|---|---|
| 14:24:16 | 14:24:17 | 14:24:58 | summarize | gemma4 | entra sin espera |
| 14:24:16 | 14:24:59 | 14:37:22 | explain_code | qwen36 | 6 trozos, 74 k chars; cede el turno a los ~127 s (`TURN_YIELD_S=120`) |
| 14:24:18 | 14:27:06 | 14:27:43 | summarize | gemma4 | cambio de modelo |
| 14:24:18 | 14:27:43 | 14:29:12 | explain_code | qwen36 | 3 trozos; cambio de modelo |
| **14:24:20** | **14:29:13** | **14:30:03** | **summarize** | **gemma4** | **la del issue; cambio de modelo** |

Las cuatro operaciones de delante suman ≈294 s de turno, que cuadra con los 291,6 s medidos.
Hubo 4 cambios de modelo (gemma4 → qwen36 → gemma4 → qwen36 → gemma4) antes de que le tocara.

## Por qué el turno alterna
`turn.evaluate` (turn.py:199-251) concede en orden de llegada; detrás de una cabeza bloqueada solo
pasa quien cumple la excepción E-1 (`_e1`, turn.py:185-196): compatible con lo que está en uso **y**
con todo lo que va delante. Con la cola intercalada gemma4/qwen36, ninguna summarize puede adelantar
a la explain_code que va delante, así que el modelo cambia en cada relevo. Es el diseño de equidad
(REQ-005), no un fallo.

## El paso a segundo plano a los 120 s
El servidor ya manda `notifications/progress` cada 20 s desde el #479 (`cancellation.middleware`,
`PROGRESS_INTERVAL_S`). La llamada no se cortó: siguió, terminó bien y el resultado llegó como
notificación de tarea. El paso a segundo plano a los 120 s lo decide Claude Code, no la falta de
progreso del servidor; `queue_saturated` (900 s sin que la cola avance) no saltó porque la cola avanzaba.

## Otras observaciones
- El «≈14493 tokens» del resultado es la estimación de tokens de Claude ahorrados (chars/2), no el
  prompt del modelo local, que fue 8701 tokens. No es un error.
- Entre 14:12 y 14:18 hay esperas de turno de 118-221 s sin ninguna entrada local que las explique:
  probablemente operaciones remotas (la Mac vía `/api/turn`), que el PC no registra (REQ-015).

## Conclusión
No hay defecto: es cola. 85 % del tiempo fue espera del turno detrás de una ráfaga de 14 llamadas con
dos modelos que se excluyen, y el orden de llegada obligó a 4 cambios de modelo.
