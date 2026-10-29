# Revisión del gate spec — concurrencia-pc-mac

Revisor: subagente independiente (`general-purpose` con el encargo de `personal-sdd-review`), sin
herramientas `local_*` (MCP caído el 2026-10-29). Dos rondas.

## Ronda 1 — aprobar con cambios (4 bloqueantes)

| # | Hallazgo | Resolución en `spec.md` |
|---|---|---|
| B1 | La muestra de `/running` es una por operación (`concurrency.py:83-89`, `:199`): desde el trozo 2 no habría `waiting_backend`; con 2 plazas, un envío borraría la marca del otro. | REQ-001/002: temporizador **por envío**, aparte de la muestra del log; `backend_wait` por envío y cada uno borra solo lo suyo. |
| B2 | `Turn.request/_wait` bloquean (`turn.py:449-525`); `release_slot` no reevalúa; no hay API para operaciones sin hilo ni limpieza de `_granted`. | REQ-011: API `enqueue`/`poll`/`expire`/`remote_flight`/`wait_change`; `release_slot`, `abandon` y `expire` reevalúan; tests existentes sin tocar. |
| B3 | REQ-025 (seguir sin turno con `expired`/429) contradecía REQ-031: más contención ⇒ más operaciones saltándose la cola. | REQ-025 en tres casos: solo un daemon inutilizable degrada; 429 = esperar; `expired` = volver a pedir antes del siguiente envío. |
| B4 | REQ-031 no verificable: faltaban el retraso del latido, la llamada en curso, y con vuelo remoto la forzada no actúa. | REQ-031 con precondición, cota `TURN_YIELD_S + heartbeat_s + HTTP_TIMEOUT + carga`, «ningún envío nuevo tras la señal», `TURN_YIELD_S=0` documentado y simulación con reloj falso. |

No bloqueantes atendidos: exención de `PortToken` solo para tres rutas POST exactas y `lease`
aleatorio de 32 bytes (REQ-010/016); `_note_queue_progress` en eventos remotos y `stalled_s` con ese
reloj (REQ-012/024); definición de «choca», todas las activas que chocan ceden y tope del servidor
para quien ignore `yield` (REQ-030); foto de `/running` al vencer el plazo, con `_LoadProbe` primero
(REQ-005, también pedido por la revisión del plan); falso `waiting_backend` por alias en la Mac
(REQ-001: si no se puede decidir, no se marca); guarda «nunca a sí mismo» (REQ-020); REQ-040
completo; `_inflight_live` para entradas remotas (REQ-014); manejadores en el threadpool (REQ-010).

Evidencia que faltaba: choque real qwen/gemma en la topología de la PC — **comprobado** (§5,
`clashes` = `True`); clave del backend en el entorno del daemon de la PC — **sin confirmar**, pasa
a paso 0 del lote 3 con alternativa (token del puerto); límite 16/8 — justificado con la medición
(2 operaciones simultáneas de la Mac) y con 429 = esperar.

## Ronda 2 — aprobado

Sin bloqueantes. El revisor comprobó contra el código las citas nuevas (`_LoadProbe`,
`server.py:1631` y `:1839`; `_require_hook_client`, `web/metrics.py:1132`). Ajustes no bloqueantes,
incorporados: `Active.granted_at` y `must_yield` añadidos a la API de REQ-011 (y al lote 2); test de
dos activas que ceden cada una a su tiempo; test de que un cliente que ignora `yield` y vuelve a
pedir queda al final (lote 3); si algún test de `test_turn*.py` mide tiempos con la reevaluación, se
aplica la regla de parada sin tocarlo.

**Evidencia exigida para cerrar la implementación** (copiada al plan): simulación de REQ-031 con
reloj falso y contraejemplo con `TURN_YIELD_S=0`; tests de la API sin bloqueo y suite del turno
intacta antes y después; enumeración de rutas, variantes, cookie, `Origin` y 403
`turn_needs_secret`; envíos simultáneos y alias sin topología; paso 0 del lote 3 (clave del backend
en el daemon de la PC); prueba en vivo PC+Mac con `turn_yields > 0`, `remote_turn: "granted"` y la
Mac visible con su `host` en el panel de la PC.
