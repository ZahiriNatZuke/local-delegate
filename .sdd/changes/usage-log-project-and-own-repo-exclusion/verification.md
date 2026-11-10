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
| REQ-005 | `tests/test_project_privacy.py` (de punta a punta: fila, relleno, evento de hook, línea del mod, `local_status`, `/api/stats`, `/api/events`, `/api/hooks`) | pass | mutantes 16 y 16a (y tres variantes de 16a) mueren (T11, abajo) |
| REQ-015 | Capturas del panel en claro y oscuro con los datos de la copia de T1, interruptor apagado y encendido | pass | T11, «Capturas» |
| REQ-022 | Suite completa con `-n 2` | ver «Commands» | T11 |
| REQ-024 | `tests/test_no_uncatalogued_text.py`, `tests/test_i18n_parity.py`, `tests/test_detect_spanish_names.py` sin excepciones nuevas | pass | mutante 66 muere; `tests/data/uncatalogued_exceptions.json` y `scripts/data/spanish_lexicon.json` sin tocar en T10/T11 |
| REQ-025 | Revisión de CHANGELOG, README, `Savings-and-metrics.md` y `Configuration.md` contra la lista de REQ-025 | pass | T10, tabla de cobertura |
| REQ-026 | Prueba en vivo con el daemon instalado | pendiente | la hace la sesión principal; pasos y cifras esperadas en «Prueba en vivo (REQ-026), preparada» |
| REQ-027 | Tabla antes/después sobre una copia nueva de la instantánea de T1, mismo `now` y mismo rango | pass | T11, «Tabla antes/después»: criterios (a) a (d) se cumplen |
| REQ-028 | Tabla de mutantes completa: 1 a 66 | pass | todos mueren salvo el 14, equivalente por diseño (ya anotado) |
| REQ-029 | `docs/wiki/Savings-and-metrics.md`, «Los medidores»: el corte del 2026-12-14 con las dos cifras junto al comando | pass | T10 |
| REQ-030 | `git diff --diff-filter=MDR --name-only origin/main...HEAD -- tests/` | pass | vacío (T11) |
| REQ-032 | `tests/test_hook_classify_endpoint.py` sin tocar y en verde | pass | 0 líneas de diff; pasa (T11) |

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

## T6 y T7 — Scripts de medición sobre la instantánea

Medido el 2026-11-10 hacia las 11:50 (hora de Uruguay) sobre dos copias privadas de la instantánea
de T1 (la de T1 queda intacta para T11), con `LOCAL_DELEGATE_LOG_DIR` y `LD_HOOK_TELEMETRY_LOG`
apuntando a la copia y `measure_plugin_adoption.py --now 2026-11-10T14:05:00+00:00`. La raíz de
proyectos es la real (solo lectura). Solo recuentos.

- **Copia A**: la instantánea tal cual la dejó T1 (relleno de `main`, sin proyecto).
- **Copia B**: la instantánea intacta más el relleno del código nuevo con el mismo `now`; los
  cruces salen iguales que en T1 (3.709 líneas; 1.076 / 181 / 57 / 7 / 2.388). Es lo que medirá T11.

Con `--include-self` las cifras coinciden con la línea base de T1 en las dos copias:

| Cifra | T1 | A `--include-self` | B `--include-self` | A por defecto | B por defecto |
| --- | ---: | ---: | ---: | ---: | ---: |
| `measure_adoption.py`: `reads` | 59.555 | 59.555 | 59.555 | 15.250 | 15.250 |
| `offered` / `blocks` / `accepted` | 3.548 / 498 / 49 | 3.548 / 498 / 49 | 3.548 / 498 / 49 | 1.455 / 184 / 25 | 1.455 / 184 / 23 |
| `total_delegations` | 1.264 | 1.264 | 1.264 | 1.264 | 483 |
| `sessions` | 95 | 95 | 95 | 29 | 29 |
| `excluded_self`: `hooks` / `usage` | — | 0 / 0 | 0 / 0 | 45.035 / 0 | 45.035 / 781 |
| `unknown_project`: `hooks` / `usage` | — | 2.180 / 1.270 | 2.180 / 151 | 2.180 / 1.270 | 2.180 / 151 |
| `delegations_by_caller`: `main` / `subagent` / `mod` / `unknown` | — | 54 / 911 / 154 / 145 | 54 / 911 / 154 / 145 | 54 / 911 / 154 / 145 | 0 / 247 / 91 / 145 |
| `delegations_by_project_kind`: `self` / `other` / `unknown` | — | 0 / 0 / 1.264 | 781 / 338 / 145 | — / 0 / 1.264 | — / 338 / 145 |
| `measure_plugin_adoption.py`: `sessions` / `with_delegation` / `pct` | 59 / 18 / 30,5 | 59 / 18 / 30,5 | 59 / 18 / 30,5 | 11 / 0 / 0,0 | 11 / 0 / 0,0 |
| `excluded_rows` (los seis motivos) | 4 / 12 / 154 / 743 / 341 / 2.126 | iguales | iguales | iguales | iguales |
| `excluded_self_sessions` | — | 0 | 0 | 48 | 48 |
| `with_subagent_delegation` / `with_mod_delegation` | — | 43 / 18 | 43 / 18 | 6 / 4 | 6 / 4 |
| `delegations_by_caller`: `main` / `subagent` / `mod` / `unknown` | — | 30 / 747 / 154 / 0 | 30 / 747 / 154 / 0 | 30 / 747 / 154 / 0 | 0 / 108 / 91 / 0 |

Lectura:

- Los eventos de hooks no dependen del relleno: sus 45.035 eventos del propio repo salen de la
  sesión de cada evento (`project_of_session`, todos son eventos de antes de T8) y los 2.180 que
  quedan sin proyecto son lecturas cuya sesión ya no tiene transcript o no tiene forma de UUID.
- Las filas del log de uso solo se apartan con el relleno nuevo (copia B): en la A no hay ninguna
  fila con tipo, y por eso allí `total_delegations` no baja.
- Corte de 90 días del 2026-12-14 (REQ-029): los dos scripts dan las dos cifras con la misma
  orden, con y sin `--include-self`; la comparable con los cortes de 14 y 30 días es la de
  `--include-self`. El aviso en la wiki es de T10.

### Control positivo (REQ-028), mutantes de T6 y T7

Cada mutante se aplicó solo sobre el script, con `PYTHONDONTWRITEBYTECODE=1`, se comprobó que el
fichero cambiaba y se corrió su fichero de test entero; después se restauró el original byte a byte.

| N.º | Mutante | Test que falla por la aserción del plan | Otros tests que también caen |
| ---: | --- | --- | --- |
| 51 | No se filtran los eventos de hooks | `test_hook_events_of_the_own_repo_are_left_out`: «the reads are only those of the other session» | el del evento viejo, el de la opción por defecto, el de la salida de texto y el de una búsqueda por sesión |
| 52 | No se filtran las filas del log de uso | `test_usage_rows_of_the_own_repo_are_left_out`: «total_delegations counts only the other one» | ninguno |
| 53 | No se resuelven los eventos viejos | `test_an_old_event_is_resolved_by_its_session`: «the old event of the self session is left out» | el de la opción por defecto, el de la salida de texto y el de una búsqueda por sesión |
| 54 | `--include-self` se ignora | `test_include_self_counts_both_sessions`: «both sessions count» | ninguno |
| 55 | `delegations_by_caller` sin el mod primero (cuenta por `caller_kind`) | `test_delegations_by_caller_counts_the_mod_first`: «the mod row sums in mod» | ninguno |
| 56 | `delegations_by_project_kind` cuenta lo desconocido como `other` | `test_delegations_by_project_kind_keeps_the_unknown_apart`: «the row without kind sums in unknown» | ninguno |
| 57 | No se excluyen las sesiones `self` | `test_the_sessions_of_the_own_repo_are_left_out_by_default`: «pct is 0.0 by default» | el de la opción por defecto y el de la lista `self-projects.json` |
| 58 | `--include-self` se ignora (en `main`) | `test_include_self_counts_them`: «pct is 50.0 with the option» | ninguno |
| 59 | No se miran los transcripts de subagentes | `test_a_delegation_in_a_subagent_transcript_counts_in_its_column`: «with_subagent_delegation is 1» | `test_pct_comes_only_from_the_main_thread` (su segunda aserción) |
| 60 | El mod no se atribuye por clave de sesión (compara el id en claro) | `test_a_mod_row_counts_by_the_session_key`: «with_mod_delegation is 1» | `test_pct_comes_only_from_the_main_thread` (su segunda aserción) |
| 61 | `pct` cuenta subagentes | `test_pct_comes_only_from_the_main_thread`: «pct comes only from the main thread» | ninguno |

Ningún mutante sobrevive y en todos dispara la aserción que nombra el plan.

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

## T10 — Documentación y guardianes compartidos

Rama `feat/usage-log-project-t10-t11`, desde `feat/usage-log-project`. Superficies contadas con
`git grep` (`include_tests`, `caller_kind`, `Quién delegó`, `LD_HOOK_TELEMETRY_LOG`, `excluded_tests`
fuera de `src/`, `tests/`, `scripts/`, `.sdd/` y `benchmarks/`): seis ficheros de documentación
describen el log, la telemetría o el panel, y los seis se cubren.

| Requisito de REQ-025 | CHANGELOG | README | `Savings-and-metrics.md` | `Configuration.md` |
| --- | :---: | :---: | :---: | :---: |
| Los dos campos de la fila (`caller_project`, `caller_project_kind`) | sí | sí | sí (campos del log, relleno, «El propio repo») | sí |
| Los dos de la telemetría (`project`, `project_kind`) | sí | sí | sí («El propio repo», «Sugerencias de los hooks») | sí (sección nueva y hooks) |
| La sal y el aviso de fuerza bruta; no compartirla junto a un log | sí | sí | sí | sí |
| `self-projects.json`: forma, tramos, mejor rutas, 64 KiB, en `LOG_DIR`, reiniciar el daemon, solo filas nuevas | sí | en parte (remite a la wiki) | sí | sí |
| Mismo `LOG_DIR` en todos los procesos | sí | sí (tabla de variables) | sí | sí |
| Interruptor, tres columnas y opciones de los scripts | sí | sí | sí (y tabla de APIs) | remite |
| Cambio de comportamiento: las cifras bajan y cómo recuperar la anterior | sí | sí | sí | — |
| `recompute-cost` tras actualizar | sí | sí | sí | — |
| El campo `path` sigue en claro | sí | — | sí | — |
| Corte de 90 días con las dos cifras, junto al comando (REQ-029) | sí | — | sí («Los medidores») | — |

Además: `docs/wiki/Claude-plugin.md` (la línea del mod gana `project` y `project_kind`, de dónde
salen y cuándo faltan) y `docs/recipes/claude-code-hooks.md` (las dos listas de campos de la nota y
de la telemetría). Corregido de paso en la wiki: «N del mod» pasó en T5 al `title` de la columna
Mod, y la frase «el coste y la cuota no dependen del interruptor» se precisa (el coste sí sigue al
del propio repo).

Guardianes: `test_no_uncatalogued_text.py`, `test_i18n_parity.py`, `test_detect_spanish_names.py`
y `test_wiki.py` en verde sin tocar `tests/data/uncatalogued_exceptions.json` ni el léxico: el test
nuevo no trajo palabras sin clasificar. Ninguna excepción de REQ-030.

**El corte de 90 días y `measure_cooldown.py`.** La ventana abierta el 2026-09-15 (P-4) se mide con
`measure_cooldown.py`, que cuenta saltos y fallos del backend y no aparta el propio repo: su cifra no
cambia. Las dos cifras de REQ-029 son las de `measure_adoption.py` con el mismo `--since`; la wiki
da las tres órdenes juntas.

## T11 — Integración y verificación de conjunto (sin la prueba en vivo)

### Privacidad de punta a punta (REQ-005)

`tests/test_project_privacy.py`, un solo mundo sintético: un directorio de proyecto ajeno con un
marcador en el nombre y otro propio cuyo nombre lleva el marcador de la única entrada de
`self-projects.json`. Cada superficie se escribe por su camino real (fila por `server._chat` con la
nota del hook, relleno por `recompute.run` con cruce exacto y fila del mod por clave de sesión,
evento del hook de prompt como proceso propio, línea del mod por `hook_entry.record_read`,
`local_status`, y las tres APIs con y sin `include_self`) y se busca en ella cada marcador sin
distinguir mayúsculas. Cada superficie tiene su guarda de que de verdad lleva el proyecto, y un
control previo comprueba que la búsqueda ve el marcador en la ruta del transcript.

### Mutantes de T10 y T11 (16, 16a y 66)

Cada uno solo, con `PYTHONDONTWRITEBYTECODE=1`, el fichero restaurado byte a byte (comprobado) y
`git status` limpio después. Control: el test nuevo en verde antes.

| N.º | Mutante | Muere | Aserción que dispara |
| ---: | --- | --- | --- |
| 16 | `caller_project` guarda el nombre en claro (`project_fields`) | sí | `test_neither_the_name_nor_the_list_entry_reaches_any_surface`: «the usage row toolu_now_self carries the marker» |
| 16a | la fila guarda la entrada de la lista que coincidió (`project_fields`) | sí | el mismo test, en la fila |
| 16a′ | el evento de hook guarda la lista (`_event_project`) | sí | el mismo test: «the hook telemetry carries the marker» |
| 16a″ | `local_status` imprime la lista junto a su línea | sí | el mismo test: «local_status carries the marker» |
| 16a‴ | las respuestas de `/api/stats` y `/api/events` llevan la lista | sí | el mismo test: «/api/stats carries the marker» |
| 66 | un texto nuevo del panel sin catalogar (el ⓘ del propio repo, en claro) | sí | `test_no_uncatalogued_text_outside_pending`: «Texto para personas fuera del catálogo» |

Con estos, la tabla del plan queda completa: los 66 criterios más las variantes mueren todos salvo
el 14, equivalente por diseño (arriba).

### REQ-030 y REQ-032

- `git diff --diff-filter=MDR --name-only origin/main...HEAD -- tests/`: **vacío** (contra la base
  común, `7b612ca6`). Con dos puntos (`origin/main` sin `...`) salen
  `tests/test_backend_running_on_failed_probe.py` y `tests/test_explain_code_verified_lines.py`,
  que cambió `main` después de abrir la rama (#635 y #632), no este cambio. La rama solo añade
  ficheros en `tests/` (11 nuevos).
- `tests/test_hook_classify_endpoint.py`: 0 líneas de diff y en verde; el mutante 50 ya lo hizo
  caer por `response.content == expected`.

### Tabla antes/después (REQ-027)

Medido el 2026-11-10 hacia las 12:58 (hora de Uruguay) con el código de la rama sobre una copia
**nueva** de la copia intacta de la instantánea de T1 (`snapshot-pristine`), con el mismo guion de
T1 (`baseline.py --after`), el mismo `now` (`2026-11-10T14:05:00+00:00`), el mismo rango y el mismo
fichero mensual para `local_status`. Solo recuentos.

| Cifra | Antes (T1) | Después, propio repo incluido | Después, por defecto |
| --- | ---: | ---: | ---: |
| `recompute`: líneas / cruces `exact`·`window`·`window+path`·`ambiguous`·`no_match` / casos de `N` | 3.709 / 1.076·181·57·7·2.388 / 953 | iguales | (no depende) |
| `recompute`: transcripts leídos | 1.188 | 1.195 | — |
| `/api/stats` `total.calls` | 929 | 929 | 211 |
| ahorro neto (`total.net`) | 9.901.682 | 9.901.682 | 1.766.545 |
| `mod_calls` / filas de `by_client` | 153 / 2 | 153 / 2 | 91 / 2 |
| `excluded_tests` | 2.463 | 2.463 | 2.463 |
| `excluded_self` / `self_in_range` / `unknown_project` | — | 0 / 1.018 / 12 | **718** / 1.018 / 12 |
| `main_calls` / `subagent_calls` / `mod_calls` / `unknown_caller_calls` | — | 29 / 735 / 153 / 12 (= 929) | 0 / 108 / 91 / 12 (= 211) |
| Resto del total (`backend_calls`, `chars_in`, `chars_out`, `errors`, `tokens_in`, `tokens_out`, `saved`, `returned`, `estimated_events`, `fallback_events`) | los de T1 | iguales uno a uno | 281, 4.089.071, 406.716, 6, 1.332.633, 115.423, 1.948.577, 182.032, 7, 1 |
| `/api/events` `count` | 929 | 929 | 211 |
| `/api/hooks` `total` / `read_total` / `suggested` / `excluded_tests` | 41.586 / 7.140 / 2.506 / 2.850 | iguales | iguales |
| `/api/hooks` `excluded_self` / `unknown_project` | — | 0 / 41.586 | 0 / 41.586 |
| coste: `events` / `T` | 808 / 9.736.338 | 808 / 9.736.338 | 198 / 1.766.545 |
| `local_status`: eventos / llamadas / neto / bruto / pruebas fuera | 215 / 402 / 2.418.983 / 2.566.604 / 145 | iguales | iguales, más «del propio repo (local-delegate): 122 de esos eventos» |
| `measure_adoption.py`: `reads` / `offered` / `blocks` / `accepted` / `total_delegations` / `sessions` | 59.555 / 3.548 / 498 / 49 / 1.264 / 95 | iguales | 15.250 / 1.455 / 184 / 23 / 483 / 29 |
| `measure_adoption.py` `excluded_self` (`hooks`/`usage`) / `unknown_project` | — | 0/0 / 2.180/151 | 45.035/781 / 2.180/151 |
| `measure_adoption.py` `delegations_by_caller` (`main`/`subagent`/`mod`/`unknown`) | — | 54 / 911 / 154 / 145 | 0 / 247 / 91 / 145 |
| `measure_plugin_adoption.py`: `sessions` / `with_delegation` / `pct` | 59 / 18 / 30,5 | iguales | 11 / 0 / 0,0 |
| `measure_plugin_adoption.py` `excluded_rows` (seis motivos) | 4 / 12 / 154 / 743 / 341 / 2.126 | iguales | iguales |
| `measure_plugin_adoption.py` `excluded_self_sessions` / `with_subagent_delegation` / `with_mod_delegation` | — | 0 / 43 / 18 | 48 / 6 / 4 |

Criterios del plan:

- **(a)** Con el propio repo incluido, toda cifra que ya existía es igual a la de T1. La única
  diferencia es `transcripts` (1.188 → 1.195): siete transcripts nuevos de la jornada en la raíz
  viva, la deriva admitida; no mueve ni los cruces ni `N`.
- **(b)** Por defecto, el panel difiere solo en lo que `excluded_self` explica: 211 + 2.463 + 718 =
  3.392 = 929 + 2.463. El coste baja con el mismo filtro (808 → 198 eventos).
- **(c)** `excluded_self > 0` en el panel (718), en `measure_adoption.py` (45.035 eventos y 781
  filas) y en `measure_plugin_adoption.py` (48 sesiones). En `/api/hooks` es 0, como debe: los
  41.586 eventos de la instantánea son de antes de T8 y no traen `project_kind`, así que son
  `unknown` y se quedan (REQ-012); solo `measure_adoption.py` resuelve los viejos por su sesión.
- **(d)** Las cuatro columnas suman `calls` en las dos columnas (929 y 211).

**Reparto `self` / `other` / `unknown`** tras el relleno (`attribution.project_kind` sobre las filas
fundidas por `cost.merge`): todas las filas de la copia, 1.094 / 388 / 2.357 (las 2.357 incluyen
las pruebas; igual que en T4); fuera de pruebas, 781 / 338 / 151. En el rango del panel, 1.018
`self` (718 fuera de pruebas), 199 `other` y 12 sin tipo.

### Capturas (REQ-015)

Panel servido desde el worktree en un puerto que asigna el sistema (nunca el 9393), leyendo solo la
copia, sin backend, rango «Últimos 30 días» del navegador (por eso el número del interruptor es 720
y no 718: el rango del navegador acaba hacia las 13:00 y no a las 11:00). Tema claro y oscuro,
interruptor apagado y encendido: controles, KPIs, «Quién delegó» y el diálogo del ⓘ. Fuera del repo,
en el scratchpad de la sesión: `t11/captures/t11-{controls,kpis,clients}-{light,dark}-{off,on}.png`
y `t11/captures/t11-dialog-{light,dark}.png`. Apagado: Hilo principal 0, Subagentes 108, Mod 91,
Sin dato 12; encendido: 29 / 736 / 154 / 12; legibles en los dos temas.

### Prueba en vivo (REQ-026), preparada

La hace la sesión principal. Todas las horas, en hora de Uruguay; el log escribe en UTC y su
fichero mensual va por mes UTC.

0. **Preparación.** Paquete instalado desde el árbol de la rama, `uv tool install --force .`;
   reiniciar el daemon (`schtasks /Run` de su tarea) y hacer `/mcp` en Claude Code. Comprobar que
   `local-delegate --version` es el del árbol. Que nadie más delegue durante la ventana: ni agentes
   en segundo plano ni el mod (no abrir ficheros grandes). Cada sesión hace **una** delegación, con
   `text`. La sesión «del otro proyecto» se abre en un directorio cuyo nombre no lleve
   `local-delegate` como tramo (ojo: los worktrees de `.claude/worktrees` del repo son `self`).
1. `local-delegate test-window start --label own-repo-live`. Anotar el id y el instante de inicio
   (`INICIO`, en ISO UTC, p. ej. `2026-11-10T19:30:00Z`).
2. Una delegación desde la sesión del repo (p. ej. `local_summarize` con `text` corto) y otra desde
   la sesión del otro directorio. Anotar el id de sesión de la del repo (`SID`, el nombre del
   transcript en `~/.claude/projects/<dir>/`).
3. Las dos filas, sin imprimir rutas:

   ```bash
   uv run python -c "import json,re,sys; from pathlib import Path; from local_delegate import config; f=sorted(Path(config.LOG_DIR).glob('usage-*.jsonl'))[-1]; rows=[json.loads(l) for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]; rows=[r for r in rows if r.get('ts','')>=sys.argv[1]]; [print(r.get('tool'), r.get('caller_project_kind'), bool(re.fullmatch('[0-9a-f]{16}', r.get('caller_project',''))), any(('/' in str(r.get(k,''))) or ('\\\\' in str(r.get(k,''))) for k in ('caller_project','caller_project_kind'))) for r in rows]; print('distintos:', len({r.get('caller_project') for r in rows}))" INICIO
   ```

   Esperado: dos líneas, una `self True False` y otra `other True False`, y `distintos: 2`. Si el
   corte de mes UTC cae dentro de la ventana, mirar también el fichero anterior.
4. `curl -s "http://127.0.0.1:9393/api/stats?from=INICIO&include_tests=1"`: `excluded_self == 1` y
   `total.calls == 1`. Con `&include_self=1` además: `total.calls == 2` y `excluded_self == 0`.
5. `curl -s "http://127.0.0.1:9393/api/stats?session=SID&include_tests=1"`: `total.calls >= 1` y
   `excluded_self == 0`.
6. Si el mod registró alguna decisión en la sesión del repo durante la ventana, su línea de
   telemetría (`LD_HOOK_TELEMETRY_LOG`) lleva `project_kind: "self"` y el mismo `project` que la
   fila `self` del paso 3. Si no hubo ninguna, anotarlo y no forzarla.
7. `local-delegate test-window stop <id>`; comprobar que no queda ningún proceso ni espera.

Si no se puede garantizar que nadie más delegue, los pasos 4 y 5 se hacen solo con `session=` para
cada una de las dos sesiones (la del repo y la del otro directorio: las dos `total.calls >= 1` y
`excluded_self == 0`) y se anota por qué. La instantánea de T1 y sus copias (`t1/`, `t11/snap`) se
borran después de la prueba en vivo, cuando la sesión principal dé la tabla por buena.

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
| T6/T7: `pytest -n 2` de los dos ficheros nuevos y de `test_measure_adoption`, `test_measure_plugin_adoption`, `test_measure_cooldown`, `test_hook_boundaries`, `test_telemetry_concurrent_writes` y `test_detect_spanish_names` | sí | pass | 149 passed, 1 skipped |
| T6/T7: `ruff check` y `ruff format --check` de los cuatro ficheros | sí | pass | «All checks passed!» y «4 files already formatted» |
| T10/T11: `pytest -n 2` del test nuevo y de los guardianes (`detect_spanish_names`, `no_uncatalogued_text`, `i18n_parity`, `wiki`, `hook_classify_endpoint`) | sí | pass | 146 passed |
| T11: `pytest -n 2` suite completa (una corrida, con el cerrojo de comandos pesados) | sí | pass | 7.021 passed, 31 skipped y 1 failed: `test_build_hook.py::test_sdist_carries_what_regenerates_the_mod`, por un `register.js` generado e ignorado que quedó en el worktree (el sdist de un worktree no aplica `.gitignore`, trampa ya conocida). Borrado el fichero, el test pasa (2 passed); no lo causa el cambio |
| T10/T11: `ruff check` y `ruff format --check` del test nuevo | sí | pass | «All checks passed!» |

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
- **T6, `unknown_project.hooks`** cuenta solo las lecturas que quedan (el denominador), no todos
  los eventos de hooks: contado sobre todos, `test_a_file_the_hook_could_not_size_is_not_a_read`
  (existente) fallaba, porque las líneas `no_file` cambiaban esa cifra y el test exige que solo
  cambie `not_reads`. `excluded_self.hooks` sí cuenta todos los eventos apartados, igual que
  `excluded_tests.hooks`.
- **T6, tope de la búsqueda**: el script llama a `project_of_session` con 10 s de tope
  (`SESSION_SEARCH_BUDGET_S`) en vez de los 50 ms del hook, una vez por sesión y corrida
  (`SessionProjects`): con el tope del hook, un disco frío dejaría sesiones como `unknown` al azar.
  Solo lee el tipo (`project_kind_of`); nunca crea la sal en el `LOG_DIR` que mide.
- **T7, `delegations_by_caller`**: cuenta las filas de Claude Code del periodo fuera de pruebas y
  ventanas (motivos de `exclusion` `None`, `plugin`, `subagent` y `no_tool_use_id`), sin las del
  propio repo por defecto, con `caller_column` sobre la fila fundida por `cost.merge_row`.
  `excluded_rows` no cambia (no gana un motivo `self`), para que sus seis cifras sigan siendo
  las de T1. `with_subagent_delegation` busca los `tool_use_id` del modelo, incluidos los de
  subagente; `with_mod_delegation`, la `caller_session_key` de las filas del mod. Las dos, como
  `with_delegation`, desde el comienzo del periodo y sin final.
- **T10, ficheros fuera de la lista del plan**: `docs/wiki/Claude-plugin.md` y
  `docs/recipes/claude-code-hooks.md`, porque también describen los campos de la nota, de la línea
  del mod y de la telemetría (recuento de superficies con `git grep`). Solo documentación.
  `scripts/data/spanish_lexicon.json` no hizo falta.
- **T11, REQ-030 con tres puntos**: el diff contra `origin/main` a secas lista dos tests que cambió
  `main` después de abrir la rama; la comprobación correcta es contra la base común
  (`origin/main...HEAD`), y da vacío.
- **T11, la instantánea no se borra todavía**: queda para después de la prueba en vivo, por si la
  sesión principal quiere repetir alguna cifra.
- **T6/T7, léxico**: no hizo falta tocar `scripts/data/spanish_lexicon.json`; dos palabras nuevas
  sin clasificar (`callers`, `puts`) se evitaron renombrando una variable y un test.
