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

## Commands

<!-- One row per command declared in .sdd/project.json (test, lint, typecheck, build, format, ...).
Without a declaration, list what was run. Never invent a command. -->

| Command | Run | Result | Evidence |
| --- | --- | --- | --- |
| `pytest` de los cuatro ficheros nuevos | sí | pass | 108 passed |
| `pytest` de los ficheros existentes más cercanos (transcripts, recompute ×3, attribution, hook_common, quota, density, valuation, filtro de sesión del panel; hook_boundaries, hook_legacy_names, f1_conformance, no_uncatalogued_text, correlation, clients) | sí | pass | 136 y 150 passed |
| `pytest -n 2` suite completa | ver PR | — | la primera corrida la paró Claude Code por falta de memoria de la máquina (no por el cambio); resultado en el PR |
| `ruff check .` y `ruff format --check .` | sí | pass | «All checks passed!» y «461 files already formatted» |

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
- `hook_common` expone, además de `project_identity` y `project_of_session`, las piezas que usa el
  relleno: `project_directory`, `project_fields`, `project_salt`, `self_project_entries`,
  `normalize_project_name` y `projects_root`.
