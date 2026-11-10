# Verification: Log de uso con proyecto (hash y tipo) y mediciones que apartan el propio repo

## Environment

- Revision: rama `feat/usage-log-project` desde `main` en `7b612ca6` (T1 medido con ese código, antes de tocar nada).
- Relevant runtime and tool versions: Python 3.11 del `.venv` del repo, con `PYTHONPATH=src` del worktree; Windows 11.

## Evidence

<!-- One row per requirement. Result is pass, fail or skip; skip needs evidence explaining why. -->

| Requirement | Check performed | Result | Evidence |
| --- | --- | --- | --- |
| REQ-001 | `tests/test_project_identity.py` (hash, rutas no válidas, regla léxica, subagente) y mutantes 1, 2 y 3 | pass | 57 tests en verde; los tres mutantes mueren (tabla de mutantes) |
| REQ-002 | `tests/test_project_identity.py` (tipo, lista, tramos, rutas, `ñ`, tope de 64 KiB) y mutantes 4 a 7d | pass | todos los mutantes mueren |
| REQ-003 | `tests/test_project_identity.py` (creación atómica, carrera determinista, reparación, sin sal, caché por ruta, entorno del proceso) y mutantes 8 a 12 | pass | todos los mutantes mueren |
| REQ-004 | `tests/test_usage_log_project.py`: los cuatro caminos de `_log_event` (`_chat`, `_chat_chunked`, `_chat_map_reduce`, `_log_stopped`) por principal, subagente y mod; sin id, sin nota, nota caducada | pass | mutantes 13 y 15 mueren; el 14 sobrevive (equivalente, ver abajo) |
| REQ-006 | `tests/test_usage_log_project.py`: regla que lanza; espía de `open`, `io.open`, `os.stat`, `os.scandir` y `os.listdir` | pass | mutantes 17 y 18 mueren |
| REQ-007 | `tests/test_backfill_project.py` sobre un mundo de test con `recompute.run` | pass | mutantes 19 a 23 mueren |
| REQ-008 | `tests/test_caller_column.py` | pass | mutantes 28 y 29 mueren |
| REQ-023 | `tests/test_usage_log_project.py::test_a_note_of_an_older_hook_is_enough` | pass | mutante 65 muere |
| REQ-031 | `tests/test_backfill_project.py` (fila del mod, `match` intacto, cruce y clave distintos, sesión en dos directorios, sin clave, sesión perdida) | pass | mutantes 24 a 27 mueren |
| REQ-027 | Línea base «antes» de T1 (abajo) | parcial | la columna «después» es de T11 |

## T1 — Instantánea y línea base («antes», código de `main`)

- Instantánea tomada el 2026-11-10 a las 11:06 (hora de Uruguay), fuera del repo, en el directorio
  temporal de la sesión: los `usage-*.jsonl`, los `attribution-*.json` y `atribucion-*.json`,
  `test-windows.json`, los dos ficheros de agregados de coste, `clients.jsonl`, `read-hook.json`,
  `language.json` y el fichero de telemetría de hooks. Sin `daemon.json`, credenciales ni tokens.
  Se guarda además una copia intacta para repetir el relleno de `main` si hiciera falta (plan,
  criterio (a)). Se borra en T11.
- `now` del relleno: 2026-11-10 11:05 de Uruguay (`2026-11-10T14:05:00+00:00`, valor pasado tal
  cual a `recompute.run`).
- Rango del panel: del 2026-10-11 11:00 al 2026-11-10 11:00 de Uruguay (parámetros
  `from=2026-10-11T14:00:00Z`, `to=2026-11-10T14:00:00Z`); el reloj del coste (`metrics._now`)
  fijado al mismo `now`.
- `local_status`: con `LOCAL_DELEGATE_LOG` en el fichero mensual `usage-202611.jsonl` de la copia;
  el sondeo del backend se sustituyó por un «caído» de mentira (sin llamadas al backend).
- Volumen de la copia: 3.839 filas de uso (117 + 18 + 143 + 3.201 + 360 por mes) y 76.154 eventos
  de hooks.

| Cifra | Antes (T1) |
| --- | ---: |
| `recompute`: líneas rellenadas | 3.709 |
| `recompute`: cruces `exact` / `window` / `window+path` / `ambiguous` / `no_match` | 1.076 / 181 / 57 / 7 / 2.388 |
| `recompute`: transcripts / casos de `N` | 1.188 / 953 |
| `/api/stats` `total.calls` | 929 |
| `/api/stats` ahorro neto (`total.net`) | 9.901.682 |
| `/api/stats` `mod_calls` | 153 |
| `/api/stats` filas de `by_client` | 2 |
| `/api/stats` `excluded_tests` | 2.463 |
| `/api/events` `count` | 929 |
| `/api/hooks` `total` / `read_total` / `suggested` / `excluded_tests` | 41.586 / 7.140 / 2.506 / 2.850 |
| `/api/stats` coste: `events` / `T` | 808 / 9.736.338 |
| `local_status`: eventos del mes / llamadas al backend / neto / bruto / pruebas fuera | 215 / 402 / 2.418.983 / 2.566.604 / 145 |
| `measure_adoption.py --json`: `reads` / `offered` / `blocks` / `accepted` / `total_delegations` / `sessions` | 59.555 / 3.548 / 498 / 49 / 1.264 / 95 |
| `measure_plugin_adoption.py` (`--now` el de arriba): `sessions` / `with_delegation` / `pct` | 59 / 18 / 30,5 |
| `measure_plugin_adoption.py` `excluded_rows`: `no_tool_use_id` / `other_client` / `plugin` / `subagent` / `test_window` / `tests` | 4 / 12 / 154 / 743 / 341 / 2.126 |

Otras cifras del total de `/api/stats` (para el criterio (a) de T11): `backend_calls` 1.882,
`chars_in` 24.726.208, `chars_out` 1.382.495, `errors` 15, `tokens_in` 7.760.097, `tokens_out`
590.899, `saved` 10.512.831, `returned` 611.149, `estimated_events` 7, `fallback_events` 2.

## T2 — Forma de los ids de sesión

Todos los nombres de transcript principal de esta máquina tienen forma de UUID en minúsculas: 353
de 353, en 40 directorios de proyecto, sin ningún id repetido entre directorios (recuento del
2026-11-10).

## T4 — Filas del mod que recuperan proyecto en la instantánea

Relleno con el código nuevo sobre una tercera copia intacta de la instantánea, con el mismo `now`
(la de T1 queda para T11). Los cruces salen idénticos a los de `main` (1.076 / 181 / 57 / 7 /
2.388): el proyecto no cambia el cruce.

| Filas | Recuento |
| --- | ---: |
| Filas del mod (`toolu_plugin_…`) | 173 |
| … con `caller_session_key` | 168 |
| … con proyecto `self` | 77 |
| … con proyecto `other` | 91 |
| … sin proyecto (`unknown`) | 5 |
| Todas las filas de la copia, por tipo tras el relleno: `self` / `other` / `unknown` | 1.094 / 388 / 2.357 |

Las 2.357 `unknown` incluyen las pruebas, que el panel ya aparta por su cuenta.

## Control positivo (REQ-028), mutantes de T2 a T4

Cada mutante se aplicó solo, con `PYTHONDONTWRITEBYTECODE=1` y el fichero restaurado byte a byte
después. Primera pasada descartada: con bytecode, un mutante de la misma longitud restaurado en el
mismo segundo dejaba un `.pyc` viejo que contaminaba los siguientes (los 24 a 27 fallaban también
por el 23). Antes de los mutantes, control: los 108 tests nuevos en verde.

| N.º | Mutante | Muere | Aserción que dispara |
| ---: | --- | --- | --- |
| 1 | el hash ignora la sal | sí | `test_two_salts_give_two_hashes`: `h1 != h2` (y la fórmula, `test_the_hash_is_the_salted_sha256…`) |
| 2 | el hash ignora el nombre | sí | `test_the_same_name_gives_the_same_hash_and_two_names_two_hashes`: `first != other` (y la fórmula) |
| 3 | se acepta una ruta fuera de la raíz | sí | `test_an_invalid_path_gives_no_field[outside]`: `== {}` |
| 4 | el tipo es siempre `other` | sí | `test_the_repo_its_worktree_and_a_subdirectory_are_self`: `== "self"` |
| 5 | la lista no se lee | sí | `test_a_clone_with_another_name_is_self_only_with_the_list`: `== "self"` |
| 6 | no se ignoran las entradas cortas | sí | `test_short_and_non_text_entries_are_ignored`: `D--work-ap` `== "other"` |
| 7 | una lista rota lanza | sí | `test_a_broken_list_is_an_empty_list_without_error`: sale `JSONDecodeError` |
| 7a | coincidencia por subcadena | sí | `test_the_match_is_by_whole_segment_not_by_substring` y `test_other_projects_are_other`: `== "other"` |
| 7b | una entrada con ruta no casa con lo que cuelga de ella | sí | `test_an_entry_with_a_path_matches_its_directory_subdirectories_and_worktrees` (también el nombre del repo, que tiene guion) |
| 7c | la normalización conserva `ñ` | sí | `test_letters_outside_ascii_are_normalized_on_both_sides`: `D--dise-o` `== "self"` |
| 7d | sin tope de tamaño | sí | `test_a_list_above_64_kib_marks_nothing`: `== "other"` |
| 8 | la creación sobrescribe una sal válida | sí | `test_when_another_process_wins_the_race_its_salt_is_the_one`: `== "d" * 64` |
| 9 | sin sal se escribe un hash sin sal | sí | `test_without_a_salt_there_is_the_kind_and_never_an_unsalted_hash`: `"caller_project" not in fields` |
| 10 | un fichero de sal vacío no se repara | sí | `test_an_empty_or_invalid_salt_file_is_repaired`: `len(repaired) == 64` |
| 11 | la sal se lee en cada llamada | sí | `test_the_salt_is_read_once_per_process`: ninguna apertura de `project-salt` |
| 12 | la caché no va por ruta | sí | `test_the_cache_goes_by_path`: `one != two` (y `test_two_salts_give_two_hashes`) |
| 13 | `resolve_call` no añade los campos | sí | `test_every_path_writes_the_project_of_the_main_session`: `caller_project_kind == "self"` |
| 14 | el subagente usa su propio directorio | **no** | equivalente, ver abajo |
| 15 | se sella con la nota caducada | sí | `test_a_stale_note_gives_no_field`: ningún `caller_*` |
| 17 | sin el `try` propio de la regla | sí | `test_a_rule_that_raises_keeps_the_rest_of_the_attribution`: falta `caller_kind` |
| 18 | la regla comprueba en disco el directorio (`Path.exists`) | sí | `test_resolving_the_project_touches_no_new_path`: los conjuntos de rutas difieren |
| 19 | `write_backfill` no enriquece el mismo rango | sí | `test_older_entries_of_the_same_rank_are_enriched`: la `exact` previa sin proyecto |
| 20 | `write_backfill` sustituye en vez de añadir | sí | `test_enriching_adds_the_fields_and_changes_no_other`: cambian `n` y otros campos |
| 21 | `BACKFILL_FIELDS` sin los campos nuevos | sí | `test_the_merged_row_takes_the_project_from_the_backfill`: la fila fundida no trae el tipo |
| 22 | `entry_for` solo da proyecto a `exact` | sí | `test_exact_window_and_window_path_entries_carry_the_project`: la `window` nueva sin proyecto |
| 23 | un rango menor enriquece a uno mayor | sí | `test_a_lower_rank_never_touches_a_higher_one`: la `exact` cambia |
| 24 | no se usa la clave de sesión | sí | `test_a_mod_row_gets_the_project_of_its_session_key` |
| 25 | la clave de sesión reescribe el `match` | sí | `test_the_session_key_does_not_rewrite_the_match`: `match == "no_match"` |
| 26 | con cruce y clave distintos gana uno | sí | `test_a_cross_and_a_key_in_different_projects_give_none`: sale `(None, None)` |
| 27 | el índice se queda con el primer directorio | sí | `test_a_session_in_two_directories_gives_none`: sale `(None, None)` |
| 28 | `caller_column` mira `caller_kind` antes que el mod | sí | `test_a_mod_row_is_mod_even_with_caller_kind_main`: `== "mod"` |
| 29 | `caller_column` da por bueno el respaldo | sí | `test_the_fallback_thread_is_not_data` y los cruces `ambiguous`/`no_match`: `== "unknown"` |
| 65 | `resolve_call` exige un campo nuevo en la nota | sí | `test_a_note_of_an_older_hook_is_enough` (y todos los de REQ-004) |

**Mutante 14 (hallazgo): sobrevive porque es equivalente con este diseño.** La regla toma como
proyecto el primer directorio bajo la raíz (`project_directory`), no `Path(transcript_path).parent.name`
de D1. El transcript propio de un subagente es `<proyecto>/<sesión>/subagents/agent-<id>.jsonl`,
dentro del mismo directorio de proyecto, así que pasarle la ruta del subagente da el mismo proyecto
que la del principal. Se eligió así a propósito: es más robusto (una ruta de subagente que llegara
por error seguiría dando el proyecto de la sesión principal). El test sí comprueba la conducta que
pide REQ-004 (el hash del subagente es el del principal y el de su directorio de proyecto). Si la
sesión coordinadora prefiere la regla literal de D1 (`parent.name` y solo profundidad 2), el
mutante pasaría a morir, a cambio de que una ruta de subagente no diera proyecto.

Un mutante de la primera pasada también sobrevivió, el 3: el caso «fuera de la raíz» del test era
menos profundo que un transcript real y lo rechazaba la comprobación de longitud, no la de prefijo.
Se corrigió el test (misma profundidad) y el mutante muere.

## T5 — Panel: propio repo fuera por defecto y tres columnas

Hecho en la rama `feat/usage-log-project-t5` (PR contra `feat/usage-log-project`). Ficheros: los
que asigna el plan (`web/metrics.py` sin tocar `/api/hook/*`, los dos `panel.json`,
`scripts/dev/capture_dashboard.py`) y los dos tests nuevos. `tests/panel_server.py` se usa tal cual.

- API: `_usage_rows` aparta primero las pruebas y después el propio repo
  (`attribution.project_kind`); `/api/stats` y `/api/events` traen `excluded_self`,
  `self_in_range` y `unknown_project`; con `session=` el filtro no se aplica; el coste recibe las
  filas sin `self` salvo con `include_self=1` o `session=`; `/api/hooks` aparta `project_kind: self`
  y trae los dos contadores (también con la telemetría apagada). El total y cada fila de
  `by_client` traen `main_calls`, `subagent_calls`, `mod_calls` y `unknown_caller_calls` con
  `attribution.caller_column`; `mod_calls` de arriba sigue igual.
- Panel: interruptor «Propio repo» junto a «Pruebas», con el número de lo apartado al lado y su ⓘ
  (sección `dlgSelf`); estado en `localStorage` (`ld-self`); `buildQuery` gana el cuarto parámetro
  opcional `includeSelf`. «Quién delegó» gana las columnas Hilo principal, Subagentes y Mod, y
  «Sin dato» solo si alguna fila la tiene. Las columnas nuevas van detrás de «Reparto» para que
  «Tokens netos» siga siendo la cuarta (la lee `test_dashboard_ui.py`); el «N del mod» que antes
  iba tras las delegaciones pasa a `title` de la celda del mod (lo sigue leyendo
  `test_dashboard_states.py::test_mod_calls_shown_apart`, sin tocar).
- Capturas en claro y oscuro, apagado y encendido, con un log sintético y el panel servido desde
  el worktree en un puerto libre (sin backend): controles, tarjeta «Quién delegó» y diálogo. Viven
  en el scratchpad de la sesión (`captures/t5-*.png`), fuera del repo.

### Mutantes de T5 (30 a 42)

Cada uno solo, con `PYTHONDONTWRITEBYTECODE=1` y `web/metrics.py` restaurado byte a byte después;
control previo: los 33 tests nuevos en verde. Mueren los 13.

| N.º | Mutante | Muere | Aserción que dispara |
| ---: | --- | --- | --- |
| 30 | `/api/events` no aplica el filtro | sí | `test_stats_and_events_leave_out_the_own_repo_with_the_same_set`: `events.meta.count == stats.total.calls` (4 ≠ 2) |
| 31 | `excluded_self` cuenta también las pruebas ya apartadas | sí | `test_shown_plus_both_excluded_counts_is_the_whole_range`: `mostradas + excluded_tests + excluded_self == 6` (da 7) |
| 32 | `unknown_project` cuenta también las `other` | sí | `test_unknown_project_counts_only_the_rows_without_a_kind`: `== 1` (da 2) |
| 33 | `include_self=1` se ignora | sí | `test_include_self_returns_every_row`: `total.calls == 4` (da 2) |
| 34 | `self_in_range` no cuenta las que son prueba | sí | `test_self_in_range_counts_the_self_row_that_is_a_test`: `== 3` (da 2) |
| 35 | el filtro se aplica también con `session=` | sí | `test_a_session_of_the_own_repo_keeps_its_figures`: `total.calls == 1` (da 0) |
| 36 | el coste recibe las filas sin filtrar | sí | `test_the_cost_follows_the_own_repo_switch_and_not_the_tests_one`: `off.estimate < on.estimate` (iguales) |
| 37 | `/api/hooks` no filtra | sí | `test_hooks_leave_out_the_self_events_by_default`: `total == 2` (da 3) |
| 38 | `/api/hooks` aparta los eventos sin campo | sí | `test_hooks_keep_the_events_without_the_field`: `total == 2` (da 0) |
| 39 | `/api/hooks` ignora `include_self=1` | sí | `test_hooks_with_include_self_count_the_self_event`: `total == 3` (da 2) |
| 40 | `buildQuery` no añade el parámetro | sí | `test_the_three_requests_carry_include_self_together[True]`: `include_self=1` en la query común |
| 41 | el estado del interruptor no se guarda | sí | `test_the_own_repo_switch_requests_all_three_and_is_remembered`: tras recargar sigue encendido (sale apagado) |
| 42 | una columna no se cuenta | sí | `test_the_four_caller_columns_add_up_to_calls`: la suma de las cuatro es `calls` (5 ≠ 6) |

## T8 y T9 — Proyecto en la telemetría de hooks, en la línea del mod y en `local_status`

Rama `feat/usage-log-project-t8-t9`, desde `feat/usage-log-project`.

- **Hooks**: `context_of` añade `project` y `project_kind` desde el `transcript_path` de la entrada
  (con `project_identity`); sin `transcript_path` toma los de la variable de contexto
  `_SESSION_PROJECT` del `hook_common` suelto, que solo pone `run_with_session_project`. Nada sale
  del `cwd`. Todo va en su propio `try`: una regla que lanza deja el evento sin los dos campos.
- **Línea del mod**: `hook_entry.record_read` resuelve, dentro de `run_with_environ`,
  `project_of_session(session_id)` (raíz de `Path.home()` del proceso, tope de 50 ms y caché de
  T2) y `project_identity` con la sal y la lista del `LOG_DIR` del proceso, y lo pasa al
  `hook_common` suelto. `classify_text`, `suggest_delegate_read.py`, `suggest_delegate_shell.py` y
  el mod no cambian: la huella de los hooks (`version_de`) no se mueve.
- **`local_status`**: cuenta, entre los eventos del mes que no son prueba, los de
  `attribution.project_kind(rec) == "self"`, y añade la línea `mcp.status.log.own_repo` solo si no
  es cero. Las cifras de eventos, llamadas y ahorro no cambian: el test compara la línea de eventos
  del mismo mes con y sin los campos nuevos.
- **Mutante 14 de T4 y `project_of_session`**: no le afecta. `project_of_session` solo devuelve
  `<raíz>/<directorio>/<id>.jsonl`, a profundidad 2 exacta, donde «el primer directorio bajo la
  raíz» y `parent.name` son el mismo; los ids sin forma de UUID no forman ninguna ruta.
- **Tiempo de la búsqueda sobre la raíz real** (40 directorios, id inexistente, el peor caso porque
  recorre todo; 20 muestras): mediana 1,15 ms, máximo 1,46 ms. Muy por debajo del tope de 50 ms.

### Mutantes de T8 y T9 (REQ-028)

Cada uno solo, con `PYTHONDONTWRITEBYTECODE=1`, sin `__pycache__` en `src/` y el fichero restaurado
byte a byte (comprobado). Control: los 22 tests de `test_hook_project.py` y los 3 de
`test_status_own_repo.py` en verde antes. Mueren los 18: los 16 del plan, con el 48 partido en dos
(uno por cada `try`) y una variante del 49c que quita también la comprobación del final. El 49 se
corrió además solo contra su test, para ver la aserción que nombra el plan.

| N.º | Mutante | Muere | Aserción que dispara |
| ---: | --- | --- | --- |
| 43 | `context_of` sin proyecto | sí | `test_each_hook_event_carries_the_project_of_its_transcript`: `line["project_kind"]` (`KeyError`) |
| 44 | `context_of` deriva el proyecto del `cwd` | sí | `test_a_hook_event_without_transcript_path_has_no_project_even_with_a_cwd`: `"project" not in line` (hook de prompt) |
| 45 | `record_read` no resuelve por `session_id` | sí | `test_the_mods_line_carries_the_project_of_its_sessions_row`: `line["project_kind"]` (`KeyError`) |
| 46 | `project_of_session` no valida el id | sí | `test_a_session_id_without_uuid_shape_gives_no_project_and_walks_nothing[x/../<id>]`: `"project" not in line` (el id llega al transcript del repo) |
| 47 | `project_of_session` se queda con el primero de dos | sí | `test_a_session_in_two_directories_gives_no_project`: `"project" not in line` |
| 48a | sin el `try` de `context_of` | sí | `test_a_rule_that_raises_leaves_the_event_without_project`: sale `RuntimeError` |
| 48b | sin el `try` de `record_read` | sí | `test_a_search_that_raises_still_writes_the_line`: sale `RuntimeError` |
| 49 | `log_dir()` lee el entorno de la petición | sí | con `-x`, primero `test_the_mods_line_carries_the_project_of_its_sessions_row`: el hash no es el de la fila; solo el test del plan, `test_the_salt_and_the_list_come_from_the_process_log_dir`: «a request chose where the salt goes» |
| 49a | la raíz sale de `current_environ()` | sí | `test_the_projects_root_is_the_process_one_not_the_requests`: `'self' == 'other'` |
| 49b | la variable se pone en la instancia del paquete | sí | `test_the_daemon_endpoint_writes_the_project_into_the_line`: `line["project_kind"]` (`KeyError`) |
| 49c | sin el tope dentro del recorrido | sí | `test_a_slow_search_stops_at_its_budget_and_the_line_has_no_project`: «the search did not stop at its budget (0.329 s)» |
| 49c′ | sin ningún tope (dentro y al final) | sí | el mismo test: `"project" not in line` |
| 49d | sin caché por `session_id` | sí | `test_a_found_session_is_not_walked_again`: «the second decision of the session walked the root again» |
| 49e | la caché guarda el «no encontrado» | sí | `test_a_session_that_shows_up_later_is_found_the_next_time`: `second["project_kind"]` (`KeyError`) |
| 50 | `classify_text` añade `project` | sí | `test_classify_matches_the_real_cli_process` (`tests/test_hook_classify_endpoint.py:196`): `response.content == expected` |
| 62 | `local_status` no cuenta el propio repo | sí | `test_the_line_counts_the_own_events_and_the_figures_do_not_change`: falta «del propio repo (local-delegate): 2 de esos eventos» |
| 63 | `local_status` resta lo `self` de la cifra | sí | el mismo test: `"eventos: 4 " in text` |
| 64 | la línea sale con recuento cero | sí | `test_without_own_events_there_is_no_line`: `SELF_ES not in text` |

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest` de los cuatro ficheros nuevos | sí | pass | 108 passed |
| `pytest` de los ficheros existentes más cercanos (transcripts, recompute ×3, attribution, hook_common, quota, density, valuation, filtro de sesión del panel; hook_boundaries, hook_legacy_names, f1_conformance, no_uncatalogued_text, correlation, clients) | sí | pass | 136 y 150 passed |
| `pytest -n 2` suite completa | ver PR | — | la primera corrida la paró Claude Code por falta de memoria de la máquina (no por el cambio); resultado en el PR |
| `ruff check .` y `ruff format --check .` | sí | pass | «All checks passed!» y «461 files already formatted» |
| T5: `pytest -n 2` de los dos ficheros nuevos y los del panel e i18n (metrics, dashboard js/states/cost/ui, hooks_telemetry_api, capture, session_filter, panel_escaping, panel_xss_ui, no_uncatalogued_text, detect_spanish_names, i18n_parity, language ×2, response_language, clients, aborted_delegations, tool_contract, site, backend_view_shared, density) | sí | pass | 661 passed, 1 skipped (tras renombrar tres identificadores que el guardián de nombres no conocía) |
| T5: `ruff check` y `ruff format --check` de los ficheros tocados | sí | pass | sin hallazgos |

## Quality checks

- [ ] Project-native tests pass.
- [ ] Lint, formatting, type checking, and build checks pass where applicable.
- [ ] Secret scanning passes.
- [ ] No unrelated changes are present.

## Deviations and residual risk

- Mutante 14 equivalente por diseño (arriba).
- **Fichero fuera de T2–T4**: `scripts/data/spanish_lexicon.json`, que el plan asigna a T10. El CI
  de la rama falló solo en `test_detect_spanish_names.py` por 23 palabras inglesas nuevas de los
  identificadores (`alnum`, `dise`, `enriched`, `enriches`, `enriching`, `fork`, `higher`, `kib`,
  `listdir`, `resolving`, `salted`, `salts`, `scandir`, `sealed`, `subdirectories`,
  `subdirectory`, `substring`, `symlinks`, `uncrossed`, `unsalted`, `walked`, `won`,
  `worktrees`). Se añadieron a `en`, solo añadiendo líneas, para dejar el CI en verde; T10 añade
  las suyas encima. Tres ids de prueba con letras repetidas (`aaaaaaaa…`) se cambiaron por dígitos
  en vez de añadirlos al léxico.
- `transcripts.read` gana un parámetro opcional `log_dir` (la sal y la lista del log que se
  rellena), y `recompute` se lo pasa; sin él, usa el `LOG_DIR` del proceso.
- T5: «N del mod» deja de ir como sufijo de las delegaciones y pasa al `title` de la celda de la
  columna Mod, porque la columna lo dice ya; el texto del catálogo no cambia. Para T10: los textos
  nuevos del panel están en `panel.self.*`, `panel.info.self`, `panel.dialog.self.title` y
  `panel.clients.col.{main,subagent,mod,unknown}`; el léxico no necesitó palabras nuevas.
- `hook_common` expone, además de `project_identity` y `project_of_session`, las piezas que usa el
  relleno: `project_directory`, `project_fields`, `project_salt`, `self_project_entries`,
  `normalize_project_name` y `projects_root`.
