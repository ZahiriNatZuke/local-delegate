# Plan (ligero) — Paso 0

Rama `feat/concurrency-log-fields`, worktree `D:/Projects/ld-wt-concurrencia`.

## Tareas

1. `config.py`: `HOST_HEADER`, `MACHINE_NAME_OVERRIDE` (`LOCAL_DELEGATE_MACHINE_NAME`),
   `clean_machine_name`, `machine_name`, `backend_headers` (= `auth_headers` + cabecera). REQ-S0-1/2.
2. Sustituir `config.auth_headers()` por `config.backend_headers()` **solo** en llamadas al backend:
   `server._post_chat`, `server._llamaswap_state`, sondas de `/models` y `/running` de `server`,
   `web/metrics.py` (`/running`, `/api/metrics/stats`), `llamaswap_api.local_backend`, `probes`,
   `autostart`. REQ-S0-2.
3. Módulo nuevo `concurrency.py`: `Trace` (fases agregadas, muestra de `/running`, `inflight_seen`),
   `ContextVar` de la operación en curso, `phase()`, `backend_starting()`, `note_inflight()`, caché de
   `/running`. REQ-S0-3/4/5/7.
4. `server.py`, cambios mínimos y localizados:
   - `_log_event`: parámetro `concurrency_trace` y `rec["host"]` / `rec["concurrency"]` (zona de
     choque con el Frente 1: solo tres líneas tras el dict base).
   - `_OperationTurn.__init__`: `self.trace = concurrency.start(role_model)`; `log_fields()` añade
     `concurrency_trace` (llega a `_log_event` por el `**op.log_fields()` que ya usan las tres
     operaciones, sin tocarlas).
   - `_waiting_for`: `phase("turn")`; `_slot`: `phase("slot")` sobre la adquisición; `_send`:
     `backend_starting` + `phase("backend")` en los dos caminos (con y sin token de cancelación).
   - `_affinity_observe`: `llamaswap_api.in_flight_requests` + `note_inflight`, contando por modelo
     igual que antes.
5. `llamaswap_api.py`: `_origin_host`, `_requests_of`, `_Stream._first_inflight`,
   `in_flight_requests`. `in_flight` y `initial_load` no cambian de contrato.
6. REQ-S0-9: `clients.origin_from_request` y `_CURRENT_ORIGIN` (puesto en `observe_client`, como el
   nombre del cliente); `concurrency.origin_fields()`; `server._inflight_start` añade
   `host`/`host_via` y `inflight_snapshot` los copia (zona de choque con el Frente 2, #477).
7. Tests `tests/test_concurrency_log.py`; docs (REQ-S0-8) y `CHANGELOG.md` (Unreleased).

## Verificación

- `ruff check`, `ruff format --check`, tests del área y la suite completa con `-n 2` bajo el cerrojo.
- Control positivo por mutante (revertir cada pieza y ver qué assert cae):

| Mutante | Test que cae | Assert |
|---|---|---|
| sin `rec["host"]` | `test_an_entry_without_an_operation_still_has_the_host`, `test_the_entry_has_host_phases…` | `KeyError: 'host'` |
| `_post_chat` con `auth_headers()` | `test_every_post_carries_the_origin_header` | `None == 'other-host'` |
| sin `phase("slot")` | `test_the_entry_has_host_phases…` | `{'backend'} == {'backend','slot'}` |
| sin `backend_starting` | `test_the_entry_has_host_phases…`, `test_no_swap…`, `test_running_is_cached…` | `KeyError: 'backend_models'` / `'model_swap'`, `call_count 0 == 1` |
| sin `phase("turn")` | `test_a_turn_wait_is_recorded_with_its_duration` | `KeyError: 'phases'` |
| sin `note_inflight` en la afinidad | `test_the_affinity_photo_feeds_inflight_seen` | `KeyError: 'inflight_seen'` |
| `inflight_snapshot` sin copiar `host` | `test_the_inflight_entry_says_where_the_call_came_from` | `KeyError: 'host'` |
| `_inflight_start` sin `origin_fields` | ídem | `KeyError: 'host'` |
| `observe_client` sin fijar el origen | `test_the_mcp_middleware_reads_the_origin_of_the_request` | `None == ('other-host','header')` |
| `_log_event` con el nombre de la máquina en vez del origen | `test_a_call_from_another_machine_logs_its_own_host` | `'pc' == 'other-host'` |

## Revisión propia (gate plan, ligero)

Aprobado por el agente: el plan no cambia ningún contrato existente (`auth_headers`, `in_flight`,
`initial_load`, `model_requested`), no toca el turno ni la plaza (solo los cronometra) y deja una
sola línea de choque con el Frente 1 en `_log_event`.
