# Medición del paso 1 — concurrencia PC+Mac (2026-10-29, 0.45.0 en las dos)

Ventanas de prueba: PC `w-20261029T145902Z` (14:59:02–15:10:58 Z), Mac `w-20261029T145751Z` (14:57:51–15:06:35 Z).

## Caminos de los clientes (paso 1 en la Mac)
- Claude Code de la Mac: **stdio** (`uvx --from local-delegate-mcp local-delegate-mcp`) → backend remoto `own-pc.<tailnet>:9292` directo (camino 2). `backend: "remote"`, `host_via: null`.
- Claude Desktop de la Mac: `mcp-remote` contra **el daemon local de la Mac** (`127.0.0.1:9393/mcp`), que a su vez va al backend de la PC: otra cola más, independiente.
- Codex: no instalado en la Mac.
- Conclusión: hoy hay hasta **tres colas sin coordinar** sobre el mismo llama-swap: daemon de la PC, cada proceso stdio de la Mac y el daemon de la Mac.

## Línea de tiempo
| UTC | Quién | Qué |
|---|---|---|
| 14:58:13 | Mac (stdio) | 2 × `local_explain_code` (rol code, qwen36-35b-a3b), ficheros de ~20–40 KB → 13 y 18 llamadas al backend (map/reduce, 3 y 2 piezas). `backend_models` a los 3 s: `qwen36-35b-a3b: starting` → `model_swap: true` (la Mac provocó la carga de qwen). |
| 14:59:24 | PC (daemon, por /mcp HTTP) | `local_summarize` 15 K chars (rol long, gemma4-26b-a4b). Turno 0 ms, plaza 0 ms, **backend 180 012 ms**. `backend_models` a los 3 s: `qwen36-35b-a3b: ready` → `model_swap: true`. |
| 14:59:48 | PC | `/api/inflight` del daemon: la llamada en `state: running` con gemma, pero llama-swap solo tenía qwen cargado: esperaba DENTRO de llama-swap y el daemon lo pintaba como «procesando». |
| 15:02:24 | PC | **Falla**: `read_timeout` («gemma4-26b-a4b no respondió en 180 s. Puede que el backend aún lo esté cargando», mensaje engañoso: la causa era el modelo de la Mac). Quedó en el log con `ok:false` (#476 OK). Recibió 8 avisos de progreso cada 20 s, todos «procesando (N s)» (#479 OK, pero el texto no distingue espera en llama-swap). |
| 15:05:48 | Mac | explain_code 1: ok, latency 455 s, wait_ms 288 677, inference_ms 166 472, slot 0 ms, `finish_reason: length` (truncado; issue #487). |
| 15:06:24 | Mac | explain_code 2: ok, latency 491 s, wait_ms 182 779, inference_ms 308 445, slot 0 ms, `finish_reason: length`. |

## Lecturas
1. **Inanición entre máquinas**: la PC no recibió el backend en 180 s. La Mac mantenía demanda continua de qwen (31 llamadas en ~8 min); llama-swap no cambia a gemma mientras haya peticiones de qwen en vuelo o llegando, así que la PC no tuvo hueco. Ningún turno lo evita porque la Mac no pasa por el de la PC.
2. **La Mac también esperó mucho dentro del backend** (183–289 s de `wait_ms`, con plaza 0): cola interna de llama-swap/llama-server con sus 4 peticiones simultáneas (2 operaciones × 2 plazas) y la de la PC intercalada.
3. **Invisible para el panel de la PC**: el daemon no vio ninguna llamada de la Mac (`/api/inflight` solo mostraba la suya); la cabecera `X-Local-Delegate-Host` sí sale de la Mac (0.45) pero el daemon de la PC no la recoge porque no pasa por él.
4. **Estado engañoso**: `state: running` y «procesando» cuando la llamada espera en llama-swap por otro modelo. El daemon ya tiene el dato para saberlo (modelo pedido ≠ cargado y `model_swap`).
5. **Mensaje de error engañoso** en el `read_timeout`: atribuye la espera a la carga del modelo.

## Qué confirma para el diseño
- Hace falta **una cola común para todo cliente del backend**, incluidos procesos stdio remotos y otros daemons. Opción B (turno con arrendamiento en el daemon de la PC, que pide todo proceso antes de llamar al backend) cubre stdio de la Mac y el daemon de la Mac si ambos lo piden; un cliente viejo que no lo pida sigue saltándoselo.
- La opción C (proxy delante de :9292) cubriría también clientes viejos sin cambios, pero ve peticiones y no operaciones: intercalaría trozos de operaciones distintas y forzaría swaps. Valorar un híbrido: B como mecanismo y, más adelante, que `:9292` por la tailnet solo se publique detrás del daemon.
- Mejoras independientes que la medición pide y son baratas: estado `waiting_backend` (pedido ≠ cargado) en inflight y en el texto de progreso; mensaje de `read_timeout` que nombre el modelo cargado que bloquea.
