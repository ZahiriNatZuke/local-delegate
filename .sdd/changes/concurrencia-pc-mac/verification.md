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
