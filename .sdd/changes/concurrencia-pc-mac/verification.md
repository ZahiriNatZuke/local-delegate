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

### Paso 0 del lote

Resuelto por decisión del usuario, sin comprobación en vivo en este lote: el lanzador del daemon
de la PC exporta `LOCAL_DELEGATE_API_KEY`, que es la misma clave que exige llama-swap y que usa la
Mac. La verificación en vivo (PC + Mac) es del lote 5.

### Contrato para el lote 4 (cliente)

- **`acquire` una vez; luego `heartbeat`.** Tras un `acquire` que crea arrendamiento (`queued` o
  `granted`), la espera y el mantenimiento siguen con `heartbeat` del mismo `lease`. `acquire` solo
  se repite tras un `expired` o una respuesta perdida (sin respuesta legible). Motivo: un
  `acquire` de una operación (`host/op`) que ya tiene arrendamiento caduca el viejo y entra al
  final de la cola; un cliente que repitiera `acquire` mientras está `queued` volvería al final en
  cada vuelta. Está también en `spec.md`, junto a REQ-012.
- **Espera larga:** `acquire` y `heartbeat` de un arrendamiento `queued` responden al cambiar el
  estado o a los `heartbeat_s`. Solo hay una espera larga abierta por arrendamiento y 16 en total:
  la petición que pasa de ahí responde `queued` al momento, así que el cliente no debe lanzar
  latidos en paralelo para el mismo `lease` (uno detrás de otro).
- **`waiting_backend` del latido:** `true`, `false`/ausente, o un objeto `{modelo: estado}` (como
  mucho 16 entradas; claves y valores saneados como `config.clean_machine_name`, el estado a 16
  caracteres), con los OTROS modelos que llama-swap tiene cargados o cargando mientras el envío
  espera (lo mismo que `SendWatch` apunta en local). Solo cuenta con el turno concedido. El daemon
  lo guarda como `backend_wait: {"remote": {...}}`, y el panel lo pinta `waiting_backend`.
- **Resto del latido:** `in_backend` (bool; con el turno concedido cuenta como llamada en vuelo
  para `TURN_MAX_S`), `chunk` (entero ≥ 0) y `phase` (`map`, `reduce` o `retry`). Cualquier otro
  campo da 400 (`extra="forbid"`).
- **Pendiente opcional para el lote 4:** que `doctor` avise de los modelos cuyo nombre lleva `:` o
  `/` (u otro carácter que `clean_machine_name` quita). El saneado los cambia y el daemon responde
  `no_turn` porque no los encuentra en su topología. No lo hice en este lote.

### Tras la revisión de seguridad y regresiones del PR #500

- **Esperas largas acotadas:** una por arrendamiento (`_waiting`) y 16 en total (`MAX_LONG_WAITS`,
  semáforo propio); la que pasa responde al momento. Antes, 60 latidos a la vez sobre un
  arrendamiento en cola dejaban `/api/inflight` en 4,19 s.
- **JSON muy anidado** (menos de 4 KB): `RecursionError` en `json.loads` → `400 bad_request`
  (antes 500).
- **`_require_turn_client` es `def` síncrona** (corre en el threadpool, nunca en el bucle de
  `/mcp`), y el token del puerto es el que recibió `PortToken` al construir la app
  (`turn_api.enable(port_token)` en `daemon.build_app`): tras una rotación no se desincronizan.
- **Solo el daemon sirve el endpoint:** las rutas siguen montadas en `metrics.app`, pero
  `daemon.build_app` las habilita (`turn_api.enable`); la web de un proceso stdio que gana el puerto
  responde 404 en `/api/turn/*`. Se eligió habilitar en vez de montar solo en el daemon porque el
  daemon monta `metrics.app` entero en `/`, y montar el router aparte exigía otra subapp FastAPI y
  rehacer la enumeración de rutas sin ganar nada.
- **El tic local no espera a la tabla:** `_tick` usa `try_reap` (`acquire(blocking=False)`) y se
  salta el tic si la tabla está ocupada; el siguiente tic o el hilo de limpieza la revisan. La E/S de
  `inflight.json` sigue bajo el cerrojo de la tabla: con el tic sin bloqueo, sacarla no compensaba.
- **`main` traído a la rama** (#498, merge sin conflictos).

#### Control positivo de los tests nuevos

| Mutante | Test que cae | Assert |
|---|---|---|
| Sin la guarda de una espera por arrendamiento | `test_many_heartbeats_on_one_queued_lease_open_one_long_wait` | «16 long waits open on one lease» (`16 <= 1`) |
| Sin tope global de esperas | `test_long_waits_have_a_global_cap` | «6 long waits open with a cap of 4» (`6 == 4`) |
| `RecursionError` fuera del `except` | `test_deeply_nested_json_under_4_kb_is_a_400` | `RecursionError` sin capturar (500) |
| El tic llama a `reap()` con bloqueo | `test_a_local_tick_does_not_wait_for_a_busy_table` | «the local tick waited 3.00 s» (`3.0 < 0.5`) |
| Servido también fuera del daemon | `test_a_stdio_process_does_not_serve_the_endpoint` | `200 == 404` |
| Token del puerto releído (no el de `PortToken`) | `test_the_port_token_is_the_one_the_port_guard_got_at_build_time` | `401 == 200` |
| Dependencia `async` | `test_the_auth_dependency_is_sync` | `assert not True` |
| `pid` distinto del daemon en la entrada `remote:` | `test_the_remote_entry_has_the_daemons_pid` | `0 == <pid>` |

#### Ejecuciones tras la revisión

- `tests/test_turn_api.py`: 46 (38 + 8 nuevos), en verde tres veces seguidas (12,8–13,1 s).
- Ficheros relevantes (turno, daemon, `web/auth`, métricas, inflight, guarda del `Host`, panel
  stdio, `waiting_backend`, wiki, CHANGELOG, aislamiento del entorno y guardianes de idioma),
  `-n 2`: 527 en verde, 1 saltado; el guardián de nombres pidió 4 palabras inglesas más, añadidas
  al léxico, y después esos guardianes dieron 90 en verde.

## Lote 4 — Cliente del turno remoto e integración en las operaciones

Rama `feat/remote-turn-client`. REQ-020..026, REQ-027 (`local_status`), REQ-030 (cliente),
REQ-032 y REQ-040..042.

### Piezas

- `remote_turn.py` (nuevo): descubrimiento (`turn_url`: `auto`/`off`/URL; una URL con usuario o
  contraseña, otro esquema o un puerto inválido no vale), guarda «a sí mismo» (loopback con el
  `WEB_PORT` propio, sin petición; o `daemon_id` igual al del `daemon.json` local, soltando el
  arrendamiento), cliente `httpx2` propio (conexión 3 s, lectura `heartbeat_s + 5`, sin seguir
  redirecciones), credencial (`LOCAL_DELEGATE_REMOTE_WEB_TOKEN`/Llavero si existe; si no, la clave
  del backend), caché de «inutilizable» por URL y motivo (60 s; 404/405 y `self`, 10 min) con un
  aviso por proceso y motivo, `RemoteLease` y la línea de `local_status`.
- `server.py`: `_OperationTurn.ensure` pide turno remoto sin topología local y con backend remoto
  (o `TURN_URL` explícita); `_waiting_for` admite la espera remota (misma contabilidad, progreso
  «en <máquina>», saturación con el reloj del daemon); `yield` y `lost` antes de cada envío;
  `release_slot` suelta el arrendamiento; `remote_turn` en el evento; `_beat_state` (lo que manda
  el latido: `in_backend`, `waiting_backend` del lote 1, `chunk`, `phase`), en memoria.
- `config.py` (`TURN_URL`, `REMOTE_WEB_TOKEN`), `token_source.remote_web_token`, `keychain`
  (servicio `local-delegate-remote-web-token`), `cancellation` (texto de progreso remoto), i18n
  es+en, CHANGELOG y `docs/wiki/Configuration.md`.

### Decisiones propias

- **`v` mayor → `unsupported`** (REQ-041), no `bad_response` (REQ-025 los lista juntos; la tabla
  de versiones mixtas manda).
- **Sin turno por daemon inutilizable no hay fase `turn`** en el evento: queda como antes del lote
  y solo `remote_turn` dice el motivo. Con turno (concedido, cancelado o saturado) la fase mide la
  espera remota.
- **Una respuesta perdida** (timeout) repite `acquire` una vez (lo permite el contrato); dos
  seguidas son `unreachable`. Cualquier excepción del transporte, no solo `HTTPError`, degrada a
  `unreachable`: el turno nunca hace fallar una delegación.
- **`op` del arrendamiento = `<pid>-<entrada>`**: con `:` el saneado del daemon juntaba `12:34` y
  `1:234` en `1234`.
- **En la suite, `TURN_URL=off` por defecto** (`tests/conftest.py`): el backend de prueba
  (`http://test-backend/v1`) es remoto y sin daemon, y con `auto` cada evento ganaba `remote_turn`
  y caían 22 tests de compatibilidad de claves. Los tests del cliente fijan `TURN_URL`.
- **`doctor` pasa al lote 5**: un check nuevo cambia el número de checks (34) que fijan tres tests
  existentes y la wiki. La nota de los modelos con `:` o `/` queda en REQ-027.
- **Ficheros reales:** el test de dos máquinas no compara hash de `~/.claude.json` ni del log
  real (el daemon instalado y Claude Code los escriben mientras corre la suite); comprueba que
  ninguna marca del test (`model-x`, `model-y`, `pc-test`, `mac-test`) aparece en ellos (en el
  log, en lo añadido desde el principio del test).

### Control positivo (mutante aplicado por script, test que cae y assert; luego revertido)

| Mutante | Test que cae | Assert |
|---|---|---|
| Sin `RemoteLease` en `ensure` | `test_one_queue_for_two_machines` | la Mac no aparece en `/api/inflight` del daemon: «the Mac exited with 0» |
| Sin hilo de latido | `test_without_heartbeat_thread_the_lease_expires` | «the lease expired: the heartbeat thread does not keep it» |
| Sin guarda «a sí mismo» por puerto | `test_self_by_port_sends_nothing` | `DID NOT RAISE Unusable` |
| Sin guarda «a sí mismo» por `daemon_id` | `test_self_by_daemon_id_releases_and_goes_without_turn` | `DID NOT RAISE Unusable` |
| Lanzador sin `sys.path.insert` | `test_one_queue_for_two_machines` | el hijo sale con código 3 («local_delegate from D:\Projects\local-delegate\src…»): `assert 3 is None` |
| Sin cesión remota en `ensure` | `test_operation_yields_before_the_next_chunk` | «the local operation never got the turn the remote one yielded» |
| Sin volver a pedir tras `expired` | `test_operation_expired_midway_asks_again_before_the_next_send` | `1 == 2` acquires |
| `release_slot` no suelta el arrendamiento | `test_operation_granted_logs_and_releases` | entrada `remote:mac-test/…` sigue en inflight |
| Sin caché de «inutilizable» | `test_each_unusable_reason_is_remembered[404]` | «the remembered reason did not spare the request» (`2 == 1`) |
| `TURN_URL` explícita gana a la topología local | `test_a_local_topology_rules_even_with_turn_url` | `op._turn is server._turn` (`None is <Turn>`) |
| `auto` pregunta con backend local | `test_local_only_use_sends_nothing` | «a local-only process created the remote turn's client» |

Un primer mutante de la guarda de topología (en `_remote_turn_url`) no hizo caer nada: `ensure`
solo llama ahí sin topología, así que esa comprobación es redundante; se sustituyó por el mutante
real («la URL explícita antes que la topología»), que sí cae.

### Tras la revisión de seguridad y regresiones del PR #502

- **`auto` solo descubre hosts privados**, decidido por el texto y sin DNS (REQ-021 corregido): IP
  de loopback, RFC 1918, 100.64/10, ULA y link-local; `.ts.net`, `.local`, `.lan`, `.home.arpa`,
  `.internal`; nombres de una sola etiqueta. Un backend público no crea el cliente ni manda nada, y
  el evento no lleva `remote_turn`; `local_status` dice `no disponible (public_host)`. El
  `BASE_URL` de la Mac (`https://own-pc.<tailnet>.ts.net:9292/v1`) queda dentro.
- **Puerto filtrado:** `ConnectTimeout` es `unreachable` en el acto, sin reintento; sin un
  `granted` previo en el proceso se recuerda 10 min (tras un `granted`, 60 s).
- **Transporte:** `trust_env=False`; cada respuesta se lee con plazo total (conexión + lectura;
  `release`, `RELEASE_READ_S` en total), tope de 64 KiB y la cancelación mirada entre fragmentos.
  Una parada a mitad del primer `acquire` suelta el arrendamiento que nombra lo ya leído.
- **Respuestas rotas:** cualquier excepción al leerlas es `bad_response`; una excepción en el
  hilo de latido marca `lost`; `in_use` (16 × 128, `[A-Za-z0-9._:/@-]`), `lease`
  (`[A-Za-z0-9_-]{1,128}`) y `heartbeat_s`/`stalled_s` no finitos, saneados.
- **Tope local de saturación** a 2 × `QUEUE_MAX_WAIT_S` aunque el daemon diga `stalled_s: 0`.
- **Guarda «a sí mismo»** también con `127.1`, cualquier 127/8, `0.0.0.0`, `localhost.` y
  `*.localhost`; `TURN_URL` sin consulta, fragmento ni ruta; aviso (una vez y en `local_status`)
  con `http://` a un host no privado.
- **Tests:** los que dejaban un arrendamiento vivo lo sueltan en un `finally`, y el fixture `env`
  falla si queda un hilo `remote-turn-heartbeat` (con `-n 2` caía
  `test_the_memory_of_an_unusable_daemon_lasts_its_time`, `3 == 2`). Un `release` desde otro hilo
  termina también un `acquire` en curso.
- **Opcional no hecho:** el tiempo perdido probando un daemon inutilizable no va a ningún campo del
  evento (`phases.turn_probe`); queda anotado para el lote 5.

#### Control positivo de los tests nuevos

| Mutante | Test que cae | Assert |
|---|---|---|
| `auto` sin la comprobación de host privado | `test_a_public_backend_with_auto_sends_nothing` | «the client was created for a public backend» |
| `ConnectTimeout` como respuesta perdida (reintenta) | `test_a_filtered_port_costs_one_request_per_ten_minutes` | `2 == 1` |
| Sin los 10 min de «nunca alcanzado» | el mismo | `3 == 1` |
| El hilo de latido no se para al soltar | `test_granted_at_once_then_released` (cierre del fixture) | «heartbeat threads left alive» |
| Sin `trust_env=False` | `test_the_environment_proxy_is_ignored` | el proxy recibió `POST … Authorization: Bearer …` |
| Sin plazo total | `test_a_dripping_daemon_does_not_hold_acquire` | «acquire took 20.2 s» |
| Sin tope de tamaño | `test_a_huge_answer_is_a_bad_response` | `DID NOT RAISE Unusable` |
| Sin cancelación entre fragmentos | `test_a_dripping_daemon_respects_cancellation` | «the cancellation waited 4.1 s» |
| `_answer` sin captura general | `test_broken_answers_degrade[position-inf]` | `OverflowError` |
| `json.loads` sin captura general | `test_broken_answers_degrade[deep-json]` | `RecursionError` |
| El hilo de latido muere en silencio | `test_an_exception_in_the_heartbeat_thread_marks_the_lease_lost` | «the heartbeat thread died in silence» |
| `lease` sin validar | `test_broken_answers_degrade[lease-bad-chars]` | `DID NOT RAISE Unusable` |
| `heartbeat_s` sin `isfinite` | `test_answers_are_cleaned` | `nan == 5.0` |
| `in_use` sin sanear | `test_answers_are_cleaned` | `'bad model'` en `in_use` |
| Sin tope local de saturación | `test_our_own_cap_saturates_when_the_daemon_says_zero` | «held the wait past our cap» |
| Guarda por dirección solo con `_is_loopback_host` | `test_self_by_address_variants[127.1]` | `assert False` |
| `_valid` acepta consulta, fragmento y ruta | `test_turn_url_with_query_fragment_or_path_is_refused[…?x=1]` | `'http://pc:9393/?x=1/' is None` |
| Sin aviso de texto plano | `test_plaintext_to_a_public_host_warns_once` | `0 == 1` |
| La parada a mitad del primer `acquire` no suelta | `test_should_stop_releases_the_queued_lease` | «the abandoned lease stayed at the daemon» |

Un primer mutante del hilo (quitar `self._stop.set()` en `release`) no hizo caer nada: el hilo
también sale porque `lease_id` queda vacío y porque `_post` mira la parada; el mutante válido es
un hilo que no se para nunca.

## Lote 5 — Verificación en vivo PC+Mac (0.47.0, 2026-10-30)

Las dos máquinas con la 0.47.0 publicada (PC: daemon reinstalado desde PyPI; Mac: `uv tool install --no-cache` + `update`, daemon de Claude Desktop reiniciado). `doctor` en la Mac: «turno remoto activo» en el daemon de la PC. Ventanas `test-window`: PC `w-20261030T200158Z` (20:01:58–20:12:17 UTC) y Mac `w-20261030T200231Z` (20:02:31–20:11:07 UTC).

**Escenario** (el de `measurement-step1.md`): a las 20:03:21 UTC la Mac lanza dos `local_explain_code` en paralelo (qwen, ficheros .ts de 20–40 KB); segundos después la PC lanza un `local_summarize` de 15 886 caracteres (gemma). Un solo modelo residente en llama-swap.

**Lo observado** (muestreo de `inflight.json` del daemon cada 2 s, 57 muestras): las dos de la Mac como `remote:<máquina>/<op>` con `host_via: "lease"`, `in_backend`, fases `map`/`reduce` y `backend_wait`; la de la PC con `local_wait: "turn"` mientras la Mac tenía el turno, y después en el backend.

| Criterio (fijado antes de medir) | Paso 1 (2026-10-29) | 0.47.0 | Cumple |
|---|---|---|---|
| Las tres operaciones visibles a la vez en la PC, las de la Mac con máquina y estado | solo la de la PC | las tres; Mac con `host` y `lease` | ✓ |
| La operación de la PC sin `read_timeout` | `read_timeout` a los 180 s | `ok`, 119 851 ms | ✓ |
| Su espera en `phases.turn`, con `phases.backend` < 60 s | backend 180 012 ms | turn 93 782 ms; backend 26 053 ms | ✓ |
| Ninguna llamada muere por el corte de 300 s | — | 94 s, 106 s, 120 s | ✓ |
| `remote_turn: "granted"` en la Mac y ningún evento duplicado | — | `granted` ×2 (turno en 105 y 64 ms); log de la PC con un único evento (el suyo) | ✓ |
| `turn_yields` ≤ 2 y `model_swap` ≤ 2 por operación | 3 de 3 con cambio | 0 cesiones; un cambio de modelo por operación | ✓ |

**Degradación:** daemon de la PC parado a las 20:07:20 UTC → la Mac delega sin turno y termina bien (`ok`, 53 645 ms, sin fase `turn`). Etiqueta `remote_turn: "bad_response"` en vez de `unreachable`: el 9393 se publica en la tailnet con un proxy HTTPS que responde 502 con el daemon caído → issue #512 (clasificar 502/503/504 sin JSON del protocolo como `unreachable`). Daemon de vuelta a las 20:09:55 → la siguiente operación sale `granted` (turno en 53 ms, `ok`, 49 945 ms).

**Observaciones:**
- `phases`, `model_swap` y `backend_models` viven en `concurrency.*`, no en el nivel superior del evento (la Mac los buscó arriba y los vio `null`; no es un fallo).
- `model_swap: true` también en la última llamada de la Mac, sin concurrencia: entre la degradación y ella se reinició el daemon de la PC, que al arrancar puede montar su modelo residente. Hipótesis sin verificar; si se repite sin reinicio, se abre tarjeta.
- Hallazgo aparte durante la actualización de la Mac: `doctor` avisa del token literal de Claude Desktop aunque el fichero sea `0600` → issue #511.

Resultado: los seis criterios se cumplen en la primera iteración; no hizo falta tocar `TURN_YIELD_S` ni `TURN_LEASE_S`.
