# Verificación — concurrencia-pc-mac

## Lote 1 — `waiting_backend`, progreso y `read_timeout` con causa

Rama `feat/concurrency-lot1-waiting-backend`. REQ-001..005, REQ-040, REQ-042.

### Control positivo (cada pieza revertida y el assert que cae)

| Mutante | Test que cae | Assert |
|---|---|---|
| Sin la rama `waiting_backend` en `_inflight_state` | `test_the_precedence_of_the_states` | `'running' == 'waiting_backend'` |
| Borrar toda la clave `backend_wait` en vez de la subclave del envío | (f) `test_the_send_that_ends_first_leaves_the_other_ones_mark` | `'running' == 'waiting_backend'` |
| Sin la guarda de parada (generación) en `SendWatch._write` | (h) `test_a_query_that_outlives_the_send_writes_nothing_after_the_cleanup` | `'backend_wait' not in {...}` |
| Muestra inmediata (retraso 0) | (d) `test_a_quick_send_queries_nothing` | `1 == 0` (consultas a `/running`) |
| Sin la rama de progreso en `progress_message` | (j) `test_the_progress_text_names_the_loaded_model` | texto «esperando a que el backend cambie de modelo…» in «procesando» |
| Texto viejo del `read_timeout` (sin foto) | `test_another_model_loaded_is_named_as_the_cause` | `None == 'model_swap'` |
| La sonda no es la primera fuente | `test_the_probes_photo_is_the_first_source` | `2 == 1` (consultas a `/running`) |
| `_slot` no para los vigilantes al soltar la plaza | `test_letting_the_place_go_stops_the_watch_of_an_abandoned_send` | `'backend_wait' not in {...}` |
| Sin la guarda «sin topología no se marca» | (i) `test_without_topology_an_absent_name_is_not_marked` | `'waiting_backend' == 'running'` |
| `read_timeout` sin cautela de alias (sin topología) | `test_without_topology_an_alias_is_not_blamed_on_a_swap` | `'model_swap' is None` |
| Vigilante con `on_wait` bajo un cerrojo global (código anterior a la revisión) | `test_a_slow_write_of_one_send_does_not_hold_up_another_sends_stop`, `test_a_stop_during_a_write_ends_with_a_clear` | `(… - …) < 0.5` (5 s esperando); «stop() waited for the write» |
| Sin deshacer la marca cuando la parada llega durante la escritura | `test_a_stop_during_a_write_ends_with_a_clear` | `[True] == [False]` |
| Mod: sin rango propio de `waiting_backend` | `status.test.ts` «a running one still wins…», «a retrying one goes before…» | `toContain('· local_translate 5 s +2 ·')` |

### Excepción a «los tests existentes no se modifican»

`tests/test_inflight_state.py:35` fijaba el conjunto exacto `{"running", "retrying", "queued"}`.
REQ-001 exige `INFLIGHT_STATES` con `waiting_backend`; la línea se amplió con ese valor y nada
más. El resto del fichero y de la suite, intactos.

### Ejecuciones

- `tests/test_waiting_backend.py` (15) y `tests/test_read_timeout_cause.py` (7): en verde.
- Área (`test_load_probe`, `test_concurrency_log`, `test_inflight_state`,
  `test_progress_and_ghost_calls`, `test_affinity`, `test_failures_integration`, `test_fallback`,
  `test_desktop_bridge` y los dos nuevos): 196 en verde.
- Mod: `build_mod` + `claude plugin test`: 149 en verde, cinco ficheros.
- Capturas del panel en claro y oscuro con una entrada `waiting_backend` simulada: en la entrega
  del lote (scratchpad de la sesión).

### Tras la revisión independiente

- El texto del `read_timeout` usa `_resolved_model_name`: sin topología, si el nombre pedido no
  aparece en `/running` no se culpa a un cambio de modelo (el texto prudente, la causa `null`).
- Cada vigilante tiene su propio cerrojo y `on_wait` se llama fuera de él. Si la parada llega
  durante una escritura, el vigilante deshace su marca, así la última escritura es un borrado. Con
  eso, el mutante «sin la guarda de parada inicial» ya no hace caer (h): esa guarda ahorra una
  escritura, y la corrección la garantiza el deshacer, cuyo control es el test de arriba.
- Chip «cargado: …» con `--amber-tx` (oscurecido en el tema claro), fondo ámbar suave y recorte
  con puntos suspensivos.

## Lote 3 — Endpoint de turno con arrendamiento en el daemon

Rama `feat/turn-lease-endpoint`. REQ-010..017, REQ-024 (lado servidor: `stalled_s` y
`_note_queue_progress`), REQ-025 (respuestas: `expired`, `no_turn`, 404, 401/403, 429) y REQ-030
(tope de `yield` en el servidor).

### Piezas

- `turn_leases.py` (nuevo, sin FastAPI): `LeaseTable` con `acquire`, `heartbeat`, `release` y
  `reap`; `DAEMON_ID` por arranque; espera larga acotada a `heartbeat_s` solo mientras está
  `queued`; temporizador de limpieza que vive mientras haya arrendamientos y gancho en cada tic de
  una espera local (`server.TURN_TICK_HOOKS`, llamado desde `_refresh_topology`).
- `web/turn_api.py` (nuevo): tres `POST` síncronos, dependencia `_require_turn_client` en el
  router, cuerpo leído con tope de 4 KB, modelos pydantic estrictos y `extra="forbid"`.
- `web/auth.py`: `TURN_ROUTES` e `is_exempt` (igualdad exacta de método y ruta) en `PortToken`.
- `server.py`: `_inflight_put`, `_inflight_patch`, `_inflight_drop` (clave dada, `_inflight_live`)
  y `TURN_TICK_HOOKS`.
- `config.py`: `TURN_LEASE_S` (30), `TURN_MAX_LEASES` (16), `TURN_SERVER` (encendido).
- `daemon.py`: `daemon_id` en `daemon.json` y `/api/daemon`.

### Decisiones propias

- `heartbeat_s = min(5, TURN_LEASE_S / 3)`: el 5 s de REQ-022 sin una variable más.
- La espera larga solo aplica a `queued`. Con el turno concedido, `yield` depende del reloj y no de
  un cambio del turno (`wait_change` no despertaría), así que el latido responde en el acto.
- Un `acquire` de una operación (`host/op`) que ya tiene arrendamiento caduca el viejo y entra al
  final de la cola: cubre «tras `yield` vuelve a pedir» y una respuesta perdida sin dejar dos
  entradas para la misma operación.
- El tope de `yield` se comprueba al responder el latido (`_status_locked`); el temporizador solo
  caduca por falta de latido. Un cliente que sigue latiendo topa con el tope ahí, y uno que deja de
  latir caduca a los 30 s igualmente (el mutante «sin tope» lo confirmó: con la comprobación
  duplicada en `reap`, quitar una no hacía caer nada).
- `TURN_SERVER=off` responde 404 con el cuerpo de FastAPI (`{"detail": "Not Found"}`), como un
  daemon viejo; la exención de `PortToken` sigue siendo exacta también con el servidor apagado.
- Los errores llevan solo un código (`{"error": "..."}`): nunca eco de la petición ni de la
  credencial.
- `waiting_backend` del latido admite `true` o `{modelo: estado}` (máx. 16, saneado); se guarda
  como `backend_wait: {"remote": {...}}` para que `inflight_snapshot` y `_inflight_state` lo lean
  igual que el de un envío local.
- FastAPI 0.161 anida los routers incluidos (`_IncludedRouter`): la enumeración del test abre
  `effective_candidates()` y mira las dependencias resueltas (`dependant`), no solo las declaradas.

### Control positivo (cada mutante aplicado a mano, test que cae y assert; luego revertido)

| Mutante | Test que cae | Assert |
|---|---|---|
| Exención por prefijo (`/api/turn/`) en vez de exacta | `test_route_variants_still_ask_for_the_port_token` | `POST /api/turn/x`: `404 == 401` |
| `_require_turn_client` acepta `Basic` | `test_basic_with_a_valid_secret_is_refused` | `200 == 401` |
| Router sin la dependencia | `test_the_turn_routes_are_exactly_three_and_all_carry_the_dependency` | `_require_turn_client in [_json_body]` |
| Sin `_note_queue_progress` al cambiar `in_backend` | `test_a_local_wait_behind_a_remote_one_is_not_saturated_while_remote_events_move` | «the local wait left the queue: QueueSaturated(...)» |
| Sin tope de `yield` | `test_an_active_remote_that_ignores_yield_expires_at_the_cap_and_queues_at_the_end` | `'yield' == 'expired'` |
| Sin espera larga | `test_queued_behind_a_clashing_local_then_granted_during_the_long_wait` | «the long wait did not wait» |
| Sin límite por host | `test_429_past_8_per_host_and_16_in_total` | `200 == 429` |

### Ejecuciones

- `tests/test_turn_api.py`: 38 tests nuevos, en verde tres veces seguidas (5,6–5,9 s cada vez).
- Suite completa (`-n 2`): 5664 en verde, 29 saltados y 2 caídos, los dos guardianes del idioma:
  `test_no_uncatalogued_text` («Not Found» literal, ahora `HTTPStatus.NOT_FOUND.phrase`) y
  `test_detect_spanish_names` (13 palabras inglesas nuevas sin clasificar, añadidas a `en` en
  `scripts/data/spanish_lexicon.json`). Tras el arreglo, esos dos ficheros y el de los tests nuevos:
  128 en verde.
- Tests existentes sin tocar.
