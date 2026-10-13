# Ola A9b — Tests `e*`–`p*`

La subola se parte en 6 lotes (D13: 1507 filas, como mucho 300 por lote y sin partir un módulo):
`A9b-1-mapping.csv` a `A9b-6-mapping.csv` (en `waves/`), aprobados por la sesión principal el
2026-10-13 con las 8 decisiones de la fase 1 tal como se recomendaron. Cada lote es un commit que
hace la sesión principal, en una rama apilada sobre el anterior. Las tablas de controles positivos,
`local_*` y PyCharm son las de todos los lotes, porque `check_wave_records.py` lee la primera tabla
de cada sección: los **6 lotes**, 17 + 25 + 23 + 19 + 27 + 40 = 151 filas `rename_refactoring` = 151
filas `pycharm` de `waves/A9b-1-mapping.csv`, `waves/A9b-2-mapping.csv`, `waves/A9b-3-mapping.csv`,
`waves/A9b-4-mapping.csv`, `waves/A9b-5-mapping.csv` y `waves/A9b-6-mapping.csv`. El cierre de la
subola está en «Cierre de A9b», al final.

- Rama: lote 1 en `sdd/english-names-a9b-1`, apilada sobre `sdd/english-names-a9a-7` (`76fe954`, A9a
  completa), commit `5fae972`; lote 2 en `sdd/english-names-a9b-2`, commit `c3ed701`; lote 3 en
  `sdd/english-names-a9b-3`, commit `3f66253`; lote 4 en `sdd/english-names-a9b-4`, commit `7f85d24`;
  lote 5 en `sdd/english-names-a9b-5`, commit `1173df6`; lote 6 en `sdd/english-names-a9b-6`, sobre
  `1173df6` · Commit del lote 6: pendiente, con el borrador en `waves/A9b-6-commit-msg.txt` (firmado
  y sin coautoría)
- Quién: un agente hizo los 6 mappings (fase 1) y, tras la aprobación, aplicó los 6 lotes (fase 2).
- Conteo base: `evidence/A9b/collect-before.txt`, 2569 tests.

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_cooldown.py::test_three_consecutive_failures_cool_the_model_for_120_s` (lote 1; usa la fixture renombrada `clock`/`path`, `_state` y `_fail`) | `src/local_delegate/cooldown.py:167`: `>= self._failures` → `> self._failures` (enfría al fallo N+1) | `assert cooled is not None` → `assert None is not None` | sí, desde copia; sha256 igual al de antes (`evidence/A9b-1/mutant.txt`) |
| `tests/test_failure_captures.py::test_the_timeout_during_loading_is_capacity` (lote 1; usa `_capture`, `_classify_capture` y las claves nuevas del envoltorio) | en `_classify_capture`, la guarda vuelve a la clave vieja (`"excepcion" in doc`), que es el error que dejó el primer reemplazo | `KeyError: 'response'` en `doc["response"]` | sí, desde copia; sha256 igual |
| `tests/test_cooldown.py` (40 tests) | `_fail` registra un fallo menos (`range(times - 1)`) | 7 fallan; el primero, `assert cooled is not None` | sí, desde copia; sha256 igual |
| `tests/test_hook_common.py::test_a_401_means_the_backend_IS_there` (lote 2; usa la anidada renombrada `_raises_401` y `_mark`/`age_s`) | `src/local_delegate/resources/hooks/hook_common.py:241`: un `HTTPError` (401) cuenta como «no hay backend» (`return True` → `return False`) | `assert common.backend_available(marker=…) is True` → `assert False is True` | sí, desde copia; sha256 igual (`evidence/A9b-2/mutant.txt`) |
| `tests/test_failure_captures.py::test_the_oom_without_profile_did_not_reach_timeout_and_stays_uncaptured` (assert negativo del lote 1 con la clave renombrada `exception`) | la captura `oom-without-profile.json` gana una clave `"exception"` | `assert "exception" not in doc` | sí, desde copia; sha256 igual |
| `tests/test_hooks_telemetry_api.py::test_counts_suggested_over_the_total` (lote 3; usa `_event(…, suggested=…)` con los kwargs renombrados) | `src/local_delegate/web/metrics.py:615`: `_aggregate_hooks` deja de sumar las sugeridas (`suggested_total += suggested` → `+= 0`) | `assert aggregate["suggested"] == 2` → `assert 0 == 2` | sí, desde copia; sha256 igual (`evidence/A9b-3/mutant.txt`) |
| `tests/test_install_timeouts.py::test_install_keeps_the_hand_set_timeout` (lote 4; usa `_home_with`, `_timeouts_of`, `CLIENTS`, `TIMEOUTS` y los argnames `client`/`mode`) | `src/local_delegate/install.py:665`: la lectura de los plazos de Claude y opencode devuelve `{}` | `assert _timeouts_of(entry, client) == TIMEOUTS[client]` → `assert {} == {'timeout': 900000}` | sí, desde copia; sha256 igual (`evidence/A9b-4/mutant.txt`) |
| `tests/test_dashboard_cost.py::test_an_old_point_expires_without_regenerating` y `::test_warning_against_a_rejection` (lote 5; leen `_texts(…)["quota"]`, la clave JS renombrada, con `env`, `_aggregates`, `_point`, `_write_log` y `_line`) | `src/local_delegate/web/metrics.py:2007`: `quotaText` del panel devuelve `[]` | `assert "faltan 1 puntos" in text` → `assert 'faltan 1 puntos' in ''` (4 asserts, 2 tests) | sí, desde copia; sha256 igual (`evidence/A9b-5/mutant.txt`) |
| `tests/test_questions.py::test_the_elicitation_schemas_keep_their_fields_and_visible_titles[ChooseModel]` (test NUEVO del lote 6) | `src/local_delegate/questions.py`: `ChooseModel` sin `Field(title="Modelo")` (el mutante M3 del hallazgo de A8a-2) | `assert form.model_json_schema() == expected` → `{'title': 'Model'} != {'title': 'Modelo'}` (1 de 3; los otros dos siguen verdes) | sí, desde copia; sha256 igual (`evidence/A9b-6/mutant.txt`) |
| `tests/test_dashboard_states.py::test_turn_wait_shown_in_panel_as_local_wait` (arreglo de la carrera, lote 6) | `src/local_delegate/server.py`, `on_wait`: `time.sleep(0.5)` entre `_inflight_turn` y `_inflight_local_wait`, que amplía la ventana de la carrera | con la condición vieja: `assert row["text"] == "en cola local"` → `'procesando' == 'en cola local'` (el fallo que se vio en el CI de Ubuntu); con el arreglo, pasa con el mismo mutante | sí, desde copia; sha256 igual. Y 30 corridas seguidas del test arreglado, bajo el cerrojo: 30 pasan (`evidence/A9b-6/race-repeat.txt`) |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué |
| --- | --- | --- |
| Agente A9b (fase 1) | `local_summarize(path=waves/A9a.md)` | lecciones y desviaciones de los 7 lotes de A9a, sin meter las 592 líneas al contexto |
| Agente A9b-1 | `local_lint_summary(path=evidence/A9b-1/pytest-full-run1.log)` | resumen de la primera corrida de la suite (3 fallos: 1 real del lote y 2 de tiempos de `test_fake_llamaswap`) |
| Agente A9b-2 | (ninguna) | la suite salió verde a la primera (47 líneas de log) y los ficheros se leyeron por franjas concretas: no hubo nada largo que resumir |
| Agente A9b-4 | (ninguna) | suite verde a la primera y comprobaciones por script AST: nada largo que resumir |
| Agente A9b-5 | (ninguna) | suite verde a la primera (Playwright incluido, bajo el cerrojo) y comprobaciones por script AST: nada largo que resumir |
| Agente A9b-6 | (ninguna) | suite verde a la primera; el detector se leyó por su JSON con un script que filtra los ficheros de A9b, y el diff de cadenas lo hizo un script AST |
| Agente A9b-3 | (ninguna) | suite verde a la primera; los ficheros se leyeron por franjas y las comprobaciones de cadenas las hizo un script AST: nada largo que resumir |

## Llamadas `mcp__pycharm__*`

| Agente | Tool | Símbolo / fichero | Resultado |
| --- | --- | --- | --- |
| A9b-1 | `rename_refactoring` | `INICIO`→`START` (`test_enfriamiento.py`) | 7 usos |
| A9b-1 | `rename_refactoring` | `Reloj`→`Clock` | 2 usos |
| A9b-1 | `rename_refactoring` | `avanzar`→`advance` | 15 usos |
| A9b-1 | `rename_refactoring` | fixture `reloj`→`clock` | 83 usos (arrastra los 32 parámetros que la piden) |
| A9b-1 | `rename_refactoring` | fixture `ruta`→`path` | 96 usos (ídem; no toca los parámetros locales `ruta` de los ayudantes) |
| A9b-1 | `rename_refactoring` | `_estado`→`_state` | 34 usos |
| A9b-1 | `rename_refactoring` | `_fallar`→`_fail` | 48 usos |
| A9b-1 | `rename_refactoring` | `_eventos`→`_events` | 11 usos |
| A9b-1 | `rename_refactoring` | `_viejo`→`_old` | 2 usos |
| A9b-1 | `rename_refactoring` | `_nuevo`→`_new` | 6 usos |
| A9b-1 | `rename_refactoring` | `_mismo_estado`→`_same_state` | 4 usos; reescribió `waves/A4.md` (devuelto a HEAD) |
| A9b-1 | `rename_refactoring` | `_escribir`→`_write` | 3 usos, solo en su fichero |
| A9b-1 | `rename_refactoring` | `_respuesta_http`→`_http_response` (`test_fallos.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_cuerpo`→`_body` | 11 usos |
| A9b-1 | `rename_refactoring` | `_captura`→`_capture` (`test_fallos_capturas.py`) | 6 usos |
| A9b-1 | `rename_refactoring` | `_modelo_cargado_al_terminar`→`_model_loaded_at_end` | 3 usos |
| A9b-1 | `rename_refactoring` | `_clasificar_captura`→`_classify_capture` | 5 usos |
| A9b-1 | `get_file_problems` | `test_cooldown.py`, `test_failures.py`, `test_failure_captures.py` | 0 errores salvo `Unresolved reference 'FileLock'` en la cadena de `monkeypatch.setattr(cooldown, "FileLock", …)`: falso positivo que ya existía (el atributo se resuelve en tiempo de ejecución) |
| A9b-2 | `rename_refactoring` | `sin_preguntar→without_asking` (fixture, `test_fallos_integracion.py`) | 8 usos |
| A9b-2 | `rename_refactoring` | `_salida→_output` (`test_hook_common.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `antiguedad_s→age_s` (parámetro de `_marca`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_marca→_mark` | 3 usos |
| A9b-2 | `rename_refactoring` | `casa→home_env` (fixture, `test_hook_legacy_names.py`) | 5 usos |
| A9b-2 | `rename_refactoring` | `temporal→temp_dir` (fixture) | 10 usos |
| A9b-2 | `rename_refactoring` | `_correr_hook_instalado→_run_installed_hook` | 4 usos |
| A9b-2 | `rename_refactoring` | `_ultimo_evento→_last_event` | 3 usos |
| A9b-2 | `rename_refactoring` | `_evento→_event` | 6 usos |
| A9b-2 | `rename_refactoring` | `relleno→padding` (parámetro de `_escribir_telemetria`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_escribir_telemetria→_write_telemetry` | 2 usos |
| A9b-2 | `rename_refactoring` | `_EVENTOS_SISTEMA→_SYSTEM_EVENTS` (`test_hook_recipes.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_correr_hook→_run_hook` | 12 usos |
| A9b-2 | `rename_refactoring` | `_correr_con_bloqueo→_run_with_block` | 5 usos |
| A9b-2 | `rename_refactoring` | `_evento_de_prompt→_prompt_event` | 1 usos |
| A9b-2 | `rename_refactoring` | `_default_del_hook→_hook_default` | 3 usos |
| A9b-2 | `rename_refactoring` | `bloquear→block` (parámetro de `_correr`, `test_hook_shell.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `_correr→_run` | 12 usos |
| A9b-2 | `rename_refactoring` | `documento→document` (fixture) | 14 usos |
| A9b-2 | `rename_refactoring` | `_motivos→_reasons` | 2 usos |
| A9b-2 | `rename_refactoring` | `TEXTO_READ→READ_TEXT` (`test_hook_shell_ruta_absoluta.py`) | 2 usos |
| A9b-2 | `rename_refactoring` | `TEXTO_SHELL→SHELL_TEXT` | 2 usos |
| A9b-2 | `rename_refactoring` | `_entorno→_env` (fixture autouse: nadie la pide por nombre) | 0 usos |
| A9b-2 | `rename_refactoring` | `_razon→_reason` | 3 usos |
| A9b-2 | `rename_refactoring` | `documento→document` (fixture) | 7 usos |
| A9b-2 | `get_file_problems` | `test_hook_recipes.py`, `test_hook_shell_absolute_path.py`, `test_failures_integration.py` | 0 errores propios: solo `Unresolved reference` en cadenas de `monkeypatch.setattr` sobre hooks cargados con `importlib` (`record`, `backend_available`, `cooled_model`), que ya estaban |
| A9b-3 | `rename_refactoring` | `_evento→_event` (`test_hooks_telemetry_api.py`) | 16 usos |
| A9b-3 | `rename_refactoring` | `_escribir→_write` | 3 usos |
| A9b-3 | `rename_refactoring` | `_etiquetas_js→_labels_js` | 2 usos |
| A9b-3 | `rename_refactoring` | `_extraer_funcion_js→_extract_js_function` | 8 usos |
| A9b-3 | `rename_refactoring` | `_evento_de_lectura→_read_event` | 11 usos |
| A9b-3 | `rename_refactoring` | `_filas_de_lectura→_read_rows` | 3 usos |
| A9b-3 | `rename_refactoring` | `_sin_cache→_without_cache` (fixture autouse) | 0 usos |
| A9b-3 | `rename_refactoring` | `_simular_instalacion_034→_simulate_install_034` (`test_install.py`) | 1 usos |
| A9b-3 | `rename_refactoring` | `_comando_del_hook_de_read→_read_hook_command` | 2 usos |
| A9b-3 | `rename_refactoring` | `_con_huerfanos→_with_orphans` | 7 usos |
| A9b-3 | `rename_refactoring` | `_comando_del_hook_de_shell→_shell_hook_command` | 1 usos |
| A9b-3 | `rename_refactoring` | `_CODEX_REESCRITO_POR_OTRO→_CODEX_REWRITTEN_BY_OTHER` | 5 usos |
| A9b-3 | `rename_refactoring` | `_claude_escribe→_claude_write` (`test_install_cabecera.py`) | 1 usos |
| A9b-3 | `rename_refactoring` | `_claude_lee→_claude_read` | 2 usos |
| A9b-3 | `rename_refactoring` | `_codex_escribe→_codex_write` | 1 usos |
| A9b-3 | `rename_refactoring` | `_codex_lee→_codex_read` | 1 usos |
| A9b-3 | `rename_refactoring` | `_opencode_escribe→_opencode_write` | 1 usos |
| A9b-3 | `rename_refactoring` | `_opencode_lee→_opencode_read` | 1 usos |
| A9b-3 | `rename_refactoring` | `CLIENTES→CLIENTS` | 12 usos |
| A9b-3 | `rename_refactoring` | `_home_con→_home_with` | 8 usos |
| A9b-3 | `rename_refactoring` | `espia_claude→claude_spy` (fixture, `test_install_clients.py`) | 6 usos |
| A9b-3 | `rename_refactoring` | `_codex_a_mano→_codex_by_hand` | 2 usos |
| A9b-3 | `rename_refactoring` | `_prepara_codex_a_mano→_prepare_codex_by_hand` | 6 usos |
| A9b-3 | `get_file_problems` | `test_install_header.py`, `test_install_clients.py`, `test_hooks_telemetry_api.py` | 0 errores |
| A9b-4 | `rename_refactoring` | `espia_opencode→opencode_spy` (fixture, `test_install_opencode.py`) | 4 usos |
| A9b-4 | `rename_refactoring` | `_borra_la_skill_de_opencode→_delete_the_opencode_skill` | 2 usos |
| A9b-4 | `rename_refactoring` | `URL_VIEJA→OLD_URL` (`test_install_plazos.py`) | 3 usos |
| A9b-4 | `rename_refactoring` | `VIEJA→OLD_VERSION` | 5 usos |
| A9b-4 | `rename_refactoring` | `NUEVA→NEW_VERSION` | 4 usos |
| A9b-4 | `rename_refactoring` | `PLAZOS→TIMEOUTS` | 18 usos |
| A9b-4 | `rename_refactoring` | `MODOS→MODES` | 3 usos |
| A9b-4 | `rename_refactoring` | `_vieja→_old_entry` | 3 usos |
| A9b-4 | `rename_refactoring` | `_claude_escribe→_claude_write` (homónimo del lote 3) | 3 usos |
| A9b-4 | `rename_refactoring` | `_claude_lee→_claude_read` | 4 usos |
| A9b-4 | `rename_refactoring` | `_codex_escribe→_codex_write` | 1 usos |
| A9b-4 | `rename_refactoring` | `_codex_lee→_codex_read` | 2 usos |
| A9b-4 | `rename_refactoring` | `_opencode_escribe→_opencode_write` | 1 usos |
| A9b-4 | `rename_refactoring` | `_opencode_lee→_opencode_read` | 2 usos |
| A9b-4 | `rename_refactoring` | `CLIENTES→CLIENTS` (homónimo del lote 3) | 11 usos |
| A9b-4 | `rename_refactoring` | `_plazos_de→_timeouts_of` | 7 usos |
| A9b-4 | `rename_refactoring` | `_home_con→_home_with` (homónimo del lote 3) | 9 usos |
| A9b-4 | `rename_refactoring` | `_diff_grande→_large_diff` (`test_map_reduce.py`) | 7 usos |
| A9b-4 | `rename_refactoring` | `_backend_con_techo→_backend_with_ceiling` | 2 usos |
| A9b-4 | `get_file_problems` | `test_install_timeouts.py`, `test_install_opencode.py`, `test_map_reduce.py` | 0 errores |
| A9b-5 | `rename_refactoring` | `_plazo_de_conexion→_connect_timeout_of` (`test_metrics.py`) | 1 usos |
| A9b-5 | `rename_refactoring` | `_resuelta→_resolved` | 13 usos |
| A9b-5 | `rename_refactoring` | `_NETO_RESTA→_NET_SUBTRACTS` | 7 usos |
| A9b-5 | `rename_refactoring` | `_SALIDA_A_FICHERO→_OUTPUT_TO_FILE` | 4 usos |
| A9b-5 | `rename_refactoring` | `_IMAGEN_POR_PATH→_IMAGE_BY_PATH` | 3 usos |
| A9b-5 | `rename_refactoring` | `_FALLO_SIN_TOKENS→_FAILURE_WITHOUT_TOKENS` | 6 usos |
| A9b-5 | `rename_refactoring` | `_extraer_funcion_js→_extract_js_function` | 10 usos |
| A9b-5 | `rename_refactoring` | `_CAMPOS_PARIDAD→_PARITY_FIELDS` | 4 usos |
| A9b-5 | `rename_refactoring` | `_fila_de_uso→_usage_row` | 5 usos |
| A9b-5 | `rename_refactoring` | `_Mezcla→_Mix` | 6 usos |
| A9b-5 | `rename_refactoring` | `_stats_de→_stats_of` | 2 usos |
| A9b-5 | `rename_refactoring` | `_sin_ok→_without_ok` | 1 usos |
| A9b-5 | `rename_refactoring` | `_acct_en_js→_acct_in_js` | 5 usos |
| A9b-5 | `rename_refactoring` | `CAMPOS_NUEVOS→NEW_FIELDS` (`test_observabilidad_respaldo.py`) | 2 usos |
| A9b-5 | `rename_refactoring` | `_linea_de→_line_of` | 2 usos |
| A9b-5 | `rename_refactoring` | `status_sin_red→status_offline` (fixture) | 7 usos |
| A9b-5 | `rename_refactoring` | `FRASES_PROHIBIDAS→FORBIDDEN_PHRASES` (`test_panel_coste.py`) | 2 usos |
| A9b-5 | `rename_refactoring` | `entorno→env` (fixture) | 26 usos |
| A9b-5 | `rename_refactoring` | `_ahora→_now` | 15 usos |
| A9b-5 | `rename_refactoring` | `_linea→_line` (también el import de `test_metrics.py`) | 18 usos |
| A9b-5 | `rename_refactoring` | `IMAGEN→IMAGE` (ídem) | 6 usos |
| A9b-5 | `rename_refactoring` | `_escribir_log→_write_log` | 11 usos |
| A9b-5 | `rename_refactoring` | `_punto→_point` (ídem) | 10 usos |
| A9b-5 | `rename_refactoring` | `_agregados→_aggregates` (ídem) | 6 usos |
| A9b-5 | `rename_refactoring` | `_extraer→_extract` | 4 usos |
| A9b-5 | `rename_refactoring` | `_FUNCIONES→_FUNCTIONS` | 2 usos |
| A9b-5 | `rename_refactoring` | `_textos→_texts` | 7 usos |
| A9b-5 | `get_file_problems` | `test_dashboard_cost.py`, `test_fallback_observability.py`, `test_metrics.py` | 0 errores propios: solo `Unresolved reference` en cadenas de `monkeypatch.setattr` (`open`, `connect`, `Client`), falsos positivos que ya estaban |
| A9b-6 | `rename_refactoring` | `_SALIDA→_EMIT` (`test_panel_estados.py`) | 2 usos |
| A9b-6 | `rename_refactoring` | `_globales→_globals` | 1 usos |
| A9b-6 | `rename_refactoring` | `BUENO→GOOD` | 9 usos |
| A9b-6 | `rename_refactoring` | `FALLIDO→FAILED` | 18 usos |
| A9b-6 | `rename_refactoring` | `CATALOGO→CATALOG` | 2 usos |
| A9b-6 | `rename_refactoring` | `_fallido→_failed` | 3 usos |
| A9b-6 | `rename_refactoring` | `_filas_tras→_rows_after` | 1 usos |
| A9b-6 | `rename_refactoring` | `_fila→_row` | 6 usos |
| A9b-6 | `rename_refactoring` | `VUELO→IN_FLIGHT` | 13 usos |
| A9b-6 | `rename_refactoring` | `_SONDEO→_POLLING` (lo que dejó A8b) | 5 usos |
| A9b-6 | `rename_refactoring` | `_sondeo_globales→_polling_globals` | 4 usos |
| A9b-6 | `rename_refactoring` | `_con→_with_running` | 16 usos |
| A9b-6 | `rename_refactoring` | `BUENA→GOOD` (`test_post_chat_caminos.py`) | 2 usos |
| A9b-6 | `rename_refactoring` | `_RespuestaDelUsuario→_UserAnswer` | 1 usos |
| A9b-6 | `rename_refactoring` | `CAMINOS→PATHS` | 6 usos |
| A9b-6 | `rename_refactoring` | `_preparar_camino→_prepare_path` | 3 usos |
| A9b-6 | `rename_refactoring` | `IDS_DE_LA_SPEC→SPEC_IDS` (`test_precios.py`) | 3 usos |
| A9b-6 | `rename_refactoring` | `FILA_OPUS_5→ROW_OPUS_5` | 2 usos |
| A9b-6 | `rename_refactoring` | `FILA_OPUS_55_LECTURA→ROW_OPUS_55_READ` | 2 usos |
| A9b-6 | `rename_refactoring` | `FILA_OPUS_55_SALIDA→ROW_OPUS_55_OUTPUT` | 2 usos |
| A9b-6 | `rename_refactoring` | `FILA_HAIKU_WEB→ROW_HAIKU_WEB` | 3 usos |
| A9b-6 | `rename_refactoring` | `FILA_PEQUENA→ROW_SMALL` | 2 usos |
| A9b-6 | `rename_refactoring` | `FILAS→ROWS` | 8 usos |
| A9b-6 | `rename_refactoring` | `_sin_precio→_without_price` | 1 usos |
| A9b-6 | `rename_refactoring` | `Respuesta→Answer` (`test_preguntas.py`) | 4 usos |
| A9b-6 | `rename_refactoring` | `contexto_limpio→clean_context` (fixture autouse) | 0 usos |
| A9b-6 | `rename_refactoring` | `_DECLARADA→_DECLARED` | 2 usos |
| A9b-6 | `rename_refactoring` | `_Sesion→_Session` | 2 usos |
| A9b-6 | `rename_refactoring` | `_montar→_mount` | 8 usos |
| A9b-6 | `rename_refactoring` | `_correr→_run` | 8 usos |
| A9b-6 | `rename_refactoring` | `probar→try_it` (tool MCP del test) | 6 usos |
| A9b-6 | `rename_refactoring` | `acepta→accepts` | 1 usos |
| A9b-6 | `rename_refactoring` | `declina→declines` | 2 usos |
| A9b-6 | `rename_refactoring` | `cancela→cancels` | 2 usos |
| A9b-6 | `rename_refactoring` | `muda→silent` | 2 usos |
| A9b-6 | `rename_refactoring` | `_responde→_reply` | 3 usos |
| A9b-6 | `rename_refactoring` | `_no_responde→_no_answer` | 1 usos |
| A9b-6 | `rename_refactoring` | `_delegar→_delegate` | 6 usos |
| A9b-6 | `rename_refactoring` | `RespuestaOpcional→OptionalAnswer` | 1 usos |
| A9b-6 | `rename_refactoring` | `responder_opcional→answer_optional` (tool MCP del test) | 2 usos |
| A9b-6 | `get_file_problems` | `test_dashboard_states.py`, `test_questions.py`, `test_pricing.py`, `test_post_chat_paths.py` | 0 errores propios: solo `Unresolved reference 'connect'` en la cadena de `monkeypatch.setattr`, que ya estaba |

## A9b-1 — capturas de `tests/fixtures/backend`, `test_enfriamiento`, `test_fallos` y `test_fallos_capturas` (aplicado)

### A9b-1 · Qué se hizo

- 17 `rename_refactoring` (tabla de arriba), en los ficheros con su nombre viejo y antes de cualquier
  edición desde fuera (lección de A5b-1).
- `make_mapping.py apply` con una copia del CSV cuyas definiciones llevan ya los ámbitos renombrados
  por PyCharm (`Reloj.avanzar` → `Clock.advance`…; si no, `apply` no encuentra la función): 232 + 65 +
  47 = 344 reemplazos.
- A mano (`apply` no lo hace): la clase anidada `BloqueoOcupado`→`BusyLock`, la anidada
  `sin_disco`→`without_disk`, los argnames de 6 `parametrize` (`neutra`, `excepcion` ×3, `datos`,
  `viejo,nuevo`, `nombre`), el atributo `ahora`→`now` y los parámetros `reloj` de `_estado` y
  `clase`/`estado`/`modelo` de `_fallar`, con los 3 kwargs `clase=`→`failure_class=` de sus llamadas.
- `git mv` de 3 módulos (`test_cooldown.py`, `test_failures.py`, `test_failure_captures.py`) y de
  las 6 capturas (`load-error.json`, `length-with-reasoning.json`, `oom-with-profile.json`,
  `oom-without-profile.json`, `request-during-load.json`, `timeout-during-load.json`); dentro de
  ellas, 13 claves del envoltorio y el valor de `case` (67 cambios); en el test, 24 lecturas y nombres
  de captura. Los ids de modelo `cap-*` no se tocan (son los de la captura real).
- `ruff format` reflowó una línea de `test_cooldown.py` (`10 ** 7` cabe ahora en una línea).
- EOL: los ficheros tocados son LF y siguen LF (`git ls-files --eol`).

### A9b-1 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/failures.py:73`: cita `tests/test_failure_captures.py`.
- `tests/test_fallos_integracion.py:5` (lote 2): cita `test_failures.py` en su docstring.

### A9b-1 · Barrido final

- AST de los 3 ficheros: ningún nombre de código con un `old` del lote; las cadenas con una clave
  vieja del envoltorio, 0.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 67 en
  textos (38 docstrings, 17 comentarios y 12 cadenas): prosa en español y valores de prueba.
  Ninguna cita entre comillas invertidas de un nombre renombrado.
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): `test_enfriamiento`,
  `test_fallos_capturas`, `BloqueoOcupado`, `_clasificar_captura`, `muestras_running`,
  `clase_esperada`… 0. Quedan `cap-error-carga` y `cap-oom-con-perfil` dentro de las capturas: son
  ids de modelo, datos (decisión 7).
- `--collect-only`: 2569 (`evidence/A9b-1/collect.txt`), los mismos 40 + 50 + 10 tests por módulo.
- Suite: 2567 passed, 2 skipped (`evidence/A9b-1/pytest-full.log`). `ruff check` y
  `ruff format --check` en verde (`evidence/A9b-1/ruff-check.txt`).
- CodeQL (aproximación AST de `a9b/codeql_like.py` sobre los 3 ficheros renombrados): 0 patrones.
  Los dos `except OSError: pass` con comentario de la fase 1 están en `test_panel_coste.py:486` y
  `test_precios.py:201`: no son de este lote, se miran en el lote que renombra esos ficheros.

### A9b-1 · Desviaciones

1. **37 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: los 32 parámetros
   `reloj` de los tests (los arrastró el `rename_refactoring` de la fixture), el atributo homónimo
   `ahora` (también existe en `_Mezcla` de `test_metrics.py`) y los parámetros homónimos de `_estado`
   y `_fallar`.
2. **Una clave del envoltorio se escapó al reemplazo por `["clave"]`**: `if "excepcion" in doc` en
   `_classify_capture` y `assert "excepcion" not in doc`. La primera hizo fallar
   `test_the_timeout_during_loading_is_capacity` (`KeyError: 'response'`). La segunda **pasaba**
   igual y había dejado de comprobar nada. Se cambiaron las dos. Lección para los lotes siguientes:
   buscar también `"clave" in` / `not in`, no solo `["clave"]` y `.get(`.
3. Primera corrida de la suite: además, 2 fallos de tiempos en `test_fake_llamaswap.py`
   (`t_unload` 4,23 > 4,0 y un 500 en vez de 502 bajo carga). Pasaron sueltos y en la segunda
   corrida completa; no son de este lote (`evidence/A9b-1/pytest-full-run1.log`).

## A9b-2 — `test_fallos_integracion`, `test_hook_common`, `test_hook_legacy_names`, `test_hook_recipes`, `test_hook_shell` y `test_hook_shell_ruta_absoluta` (aplicado)

### A9b-2 · Qué se hizo

- 25 `rename_refactoring` (tabla de arriba), antes de cualquier edición desde fuera. PyCharm no tocó
  `.sdd/` esta vez.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados (`a9b/requal.py`):
  54 + 75 + 99 + 128 + 33 + 24 = 413 reemplazos.
- A mano: el `def` de las anidadas `espia`→`spy` y `_lanza_401`→`_raises_401`, la clase anidada
  `_Respuesta`→`_Response` y los argnames de 4 `parametrize` (`preparar`, `plantilla`, `comando` ×2).
- Fuera del CSV, por el barrido de parámetros de lambdas: `lambda modelo: False` → `lambda model:
  False` en `test_hook_shell_absolute_path.py:67` (doble de `cooled_model(model)`, que se llama
  posicional).
- `git mv` de 2 módulos: `test_failures_integration.py` y `test_hook_shell_absolute_path.py`. Nadie
  los cita por ruta fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`.
- `ruff format` juntó en una línea 4 llamadas y firmas que ya caben (`test_hook_legacy_names.py`,
  `test_hook_recipes.py`, `test_hook_shell.py`). EOL: todos LF y siguen LF.
- Claves leídas de datos: este lote no renombra ninguna (ni `["x"]`, `.get("x")`, `"x" in`, `pop`
  ni `{**…}`): sus filas son solo nombres de Python.

### A9b-2 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno.

### A9b-2 · Barrido final

- AST de los 6 ficheros: ningún nombre de código, kwarg ni argname con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 94 en
  textos (51 docstrings, 20 comentarios y 23 cadenas): prosa en español y datos de prueba («este
  archivo pesa mucho», `"uno.md"`, `"cat {p} otro.md"`, los textos del aviso que afirman los tests…).
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`), los nombres propios del lote
  (`sin_preguntar`, `_correr_hook_instalado`, `_escribir_telemetria`, `TEXTO_READ`, `_lanza_401`…):
  0. Quedan `_ultimo_evento` en `test_respaldo.py` y `test_observabilidad_respaldo.py`: es otra
  función, de A9c y del lote 5.
- `--collect-only`: 2569 (`evidence/A9b-2/collect.txt`). Suite: 2567 passed, 2 skipped
  (`evidence/A9b-2/pytest-full.log`). `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre los 2 ficheros renombrados: 0 patrones.

### A9b-2 · Desviaciones

1. Ninguna fila `pycharm` pasó a `search_edit`: los 3 parámetros (`antiguedad_s`, `relleno`,
   `bloquear`) no tienen homónimos en el repo. Anotado en la línea `# Fase 2` del CSV.
2. El parámetro `modelo` de una lambda no estaba en el mapping (ni el detector ni el barrido AST de la
   fase 1 miran los argumentos de lambdas); se cambió y se anota en la misma línea `# Fase 2`.

## A9b-3 — `test_hooks_telemetry_api`, `test_install`, `test_install_cabecera` y `test_install_clients` (aplicado)

### A9b-3 · Qué se hizo

- 23 `rename_refactoring` (tabla de arriba). PyCharm reescribió 3 documentos de `.sdd/`
  (`english-names-bilingual-output/waves/A9a.md`, `js-dashboard-comportamiento/research.md` y
  `telemetria-hooks-dashboard/research.md`: citas históricas de `_con_huerfanos` y
  `_extraer_funcion_js`), devueltos a HEAD con `git show`. Los homónimos de otros ficheros
  (`CLIENTES`, `_home_con` y `_claude_escribe` de `test_install_plazos.py`, `_extraer_funcion_js` de
  `test_metrics.py`) no se tocaron.
- A mano, antes de `apply`: los parámetros `evento`/`categoria`/`sugerida` de `_evento` con sus 24
  kwargs (`a9b/kwfix.py`, por posición AST) y `fuente` de `_extraer_funcion_js`.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 233 + 169 + 54 + 83 =
  539 reemplazos.
- A mano, después: el `def` de las anidadas `_explota`→`_explodes`, `_espia`→`_spy`,
  `_no_preguntes`→`_do_not_ask` (×3) y `_revienta`→`_blows_up`; los argnames de 6 `parametrize`
  (`cliente` ×5, `esperado`); y el JS propio de `test_hooks_telemetry_api.py` (`casos`→`testCases`,
  `nodos`→`nodes`, `salida`→`results`, `caso`→`testCase`, `pares`→`aliasPairs`: 18 tokens, por
  línea, porque esos literales son concatenaciones con f-strings que `js_apply.py` no admite).
- `git mv` de `test_install_cabecera.py` → `test_install_header.py`; nadie lo cita por ruta.
- `ruff format` reflowó 3 ficheros. EOL: todos LF y siguen LF.
- **Datos que el producto escribe o lee** (bloques gestionados, settings JSON, TOML de Codex, JSON de
  opencode): comparadas las cadenas de los 4 ficheros antes y después por AST, solo cambian los
  literales JS y dos argnames de `parametrize`; ninguna clave ni texto de datos. Los valores
  `"viejo"`/`"nuevo"` de `_read_rows(fmt)` y las claves `motivo`/`bloqueo` de la telemetría vieja se
  quedan: son datos del test y claves persistidas.
- Lambdas: el barrido de sus parámetros en los 4 ficheros no encontró ninguno en español.

### A9b-3 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno.

### A9b-3 · Barrido final

- AST de los 4 ficheros: ningún nombre de código, kwarg ni argname con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 146 en
  textos (82 docstrings, 24 comentarios y 40 cadenas): prosa y datos en español; ninguna cita entre
  comillas invertidas.
- En el resto del repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): solo quedan los
  homónimos de otros lotes (`CLIENTES`, `_home_con`, `_claude_escribe` en `test_install_plazos.py`,
  lote 4; `_extraer_funcion_js` en `test_metrics.py`, lote 5).
- `--collect-only`: 2569 (`evidence/A9b-3/collect.txt`). Suite: 2567 passed, 2 skipped
  (`evidence/A9b-3/pytest-full.log`). `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre `test_install_header.py`: 0 patrones.

### A9b-3 · Desviaciones

1. **4 filas `pycharm` → `search_edit`** (parámetros homónimos `evento`, `categoria`, `sugerida` y
   `fuente`), anotado en la línea `# Fase 2` del CSV.
2. El JS del test se cambió por línea y no con `js_apply.py` (literales concatenados con f-strings);
   se comprobó con la comparación de cadenas por AST que no cambió nada más.

## A9b-4 — `test_install_opencode`, `test_install_plazos`, `test_llamaswap_config` y `test_map_reduce` (aplicado)

### A9b-4 · Qué se hizo

- 19 `rename_refactoring` (tabla de arriba), incluidos los homónimos que dejó el lote 3 en
  `test_install_plazos.py` (`CLIENTES`, `_home_con`, `_claude_escribe`). PyCharm reescribió
  `waves/A9b.md` (las citas de esos homónimos en la sección del lote 3), devuelto a HEAD con `git show`.
- A mano, antes de `apply`: el parámetro homónimo `techo`→`ceiling` de `_backend_con_techo` (def, uso
  y cita en su docstring; no tiene kwargs).
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 95 + 120 + 7 + 145 =
  367 reemplazos.
- A mano, después: el `def` de la anidada `_falla`→`_fails`, los argnames de 7 `parametrize`
  (`("texto", "esperado")`, `modo` ×2, `cliente` ×4) y la cita `` `mensaje` `` del docstring de
  `_backend_with_ceiling`.
- `git mv` de `test_install_plazos.py` → `test_install_timeouts.py`; nadie lo cita por ruta.
- `ruff format` reflowó 2 ficheros. EOL: todos LF y siguen LF.
- Datos de los clientes: comparadas por AST las cadenas de los 4 ficheros antes y después, solo
  cambian los argnames de `parametrize` y la cita del docstring; ninguna clave ni texto que escribe
  el producto. Lambdas: ningún parámetro en español.

### A9b-4 · Fuera del lote (consecuencia mecánica, aprobada)

- Ninguno.

### A9b-4 · Barrido final

- AST de los 4 ficheros: ningún nombre de código, kwarg, argname ni cita con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 78 en
  textos (37 docstrings, 31 comentarios y 10 cadenas): prosa y datos en español.
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`), los nombres propios del lote y
  los homónimos del lote 3: 0.
- `--collect-only`: 2569 (`evidence/A9b-4/collect.txt`). Suite: 2567 passed, 2 skipped
  (`evidence/A9b-4/pytest-full.log`). `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre `test_install_timeouts.py`: 0 patrones.

### A9b-4 · Desviaciones

1. **1 fila `pycharm` → `search_edit`** (el parámetro homónimo `techo`), anotado en la línea
   `# Fase 2` del CSV.

## A9b-5 — `test_metrics`, `test_observabilidad_respaldo` y `test_panel_coste` (aplicado)

### A9b-5 · Qué se hizo

- 27 `rename_refactoring` (tabla de arriba). PyCharm reescribió 10 documentos de `.sdd/` (citas
  históricas de `_Mezcla`, `_extraer_funcion_js`, `_punto`… en `coste-api-y-cuota`,
  `panel-cuentas-y-estados-honestos`, `js-dashboard-comportamiento`, `telemetria-hooks-dashboard`,
  `test-windows-out-of-metrics` y `waves/A8b.md`, `A9a.md`, `A9b.md`), devueltos a HEAD con `git show`.
  El import `from test_panel_coste import …` de `test_metrics.py` lo cambió el propio rename.
- A mano, antes de `apply`: los parámetros homónimos `fuente` (×2), `evento`, `casos` (y su cita en
  el docstring), `modelo`, `fin` y `fuente` de `_punto`, con sus kwargs (`a9b/kwfix.py`: 1, el
  `fuente="rejection"`), y los atributos `self.ahora`→`self.now` y `self.cliente`→`self.client` de
  `_Mezcla`.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 265 + 71 + 212 =
  548 reemplazos.
- A mano, después: el `def` de las anidadas `registrador`→`recorder`, `_anotar`→`_write_note`,
  `_registrar`→`_record` y `_falso`→`_fake`; el argname `valor`→`value`; y el JS propio del test con
  sus lecturas en Python: claves `coste`/`cuota`/`imagenes` → `cost`/`quota`/`images` (el objeto que
  devuelve el JS de `_textos` y sus 11 lecturas `["…"]`; ninguna lectura por `.get`, `in`, `not in`,
  `pop` ni `{**…}`), `filas`→`rowsIn` en `test_panel_coste.py` y `casos`→`testCases` en
  `test_metrics.py`. Los nombres JS nuevos no chocan con los de `metrics.HTML` (son claves de un
  objeto propio o variables del script del test).
- `except OSError: pass` de `test_panel_coste.py:486` → `with contextlib.suppress(OSError):` con el
  mismo comentario delante: el fichero cambia de nombre y CodeQL lo vería como alerta nueva si su
  `py/empty-except` no admitiera el comentario; el control (`assert attempts == ["create_connection"]`)
  sigue igual. Se añade `import contextlib`.
- `git mv`: `test_panel_coste.py` → `test_dashboard_cost.py`, `test_observabilidad_respaldo.py` →
  `test_fallback_observability.py`.
- `ruff format` reflowó 2 ficheros. EOL: los tests son LF y siguen LF.
- Comparadas por AST las cadenas antes y después: solo cambian los literales JS, el argname y dos
  citas de docstring. Se quedan, por ser datos: los valores `fallback_class="modelo"` (valor viejo
  que el producto sigue leyendo), las claves `fallos`/`hasta` del fichero viejo de enfriamiento, la
  clave `tokens_aprox` que el test busca en el código de `server.local_extract`, y las etiquetas
  `"coletilla"`/`"recibo"` de los mensajes de `test_frases_prohibidas`. Lambdas: ningún parámetro en
  español.

### A9b-5 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/web/metrics.py:1873`: el comentario JS cita `test_dashboard_cost.py` (CRLF
  conservado: 2990 `\r\n` = 2990 `\n`).

### A9b-5 · Barrido final

- AST de los 3 ficheros: ningún nombre de código, kwarg ni argname con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 313 en
  textos (114 docstrings, 141 comentarios y 58 cadenas): prosa y datos en español. Cita entre
  comillas invertidas que queda: `tokens_aprox` (clave del producto).
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`), los nombres propios del lote:
  0. Queda `_textos` en `test_recalcular.py`: es otra función, de A9c.
- `--collect-only`: 2569 (`evidence/A9b-5/collect.txt`). Suite (con Playwright, bajo el cerrojo):
  2567 passed, 2 skipped (`evidence/A9b-5/pytest-full.log`); los 121 tests del lote, sin saltos.
  `ruff check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre los 2 ficheros renombrados: 0 patrones.

### A9b-5 · Desviaciones

1. **21 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: 13 parámetros
   `entorno` (los arrastró el rename de la fixture), 6 parámetros homónimos y 2 atributos.
2. **`contextlib.suppress` en vez de `except OSError: pass`** en `test_dashboard_cost.py` (pedido
   de la sesión principal): mismo comportamiento y mismo comentario.

## A9b-6 — `test_panel_estados`, `test_post_chat_caminos`, `test_precios` y `test_preguntas` (aplicado)

### A9b-6 · Qué se hizo

- 40 `rename_refactoring` (tabla de arriba). PyCharm reescribió `waves/A3.md`, `waves/A9a.md` y
  `panel-cuentas-y-estados-honestos/verification.md`, devueltos a HEAD con `git show`.
- A mano, antes de `apply`: los parámetros homónimos `cuerpo` (`_js`), `casos` (`_fila`, con su cita
  y el `json.dumps` de la f-string), `canal` (`_Sesion`, con el kwarg `_Ctx(canal=False)`), `modelo`
  ×4 (los dobles de `ask`) y los campos `valor` de `Respuesta`/`RespuestaOpcional`, con sus lecturas
  `r.valor` y la clave `{"valor": "elegido"}` del `content` que el test valida contra el modelo.
- **Nombres de tool MCP** (lección de A9a): `@server.tool()` toma el nombre de la función, así que
  las cadenas de `call_tool` cambian con ella: `nombre="probar"` → `"try_it"` y
  `n = "responder_opcional"` → `"answer_optional"`. Anotado en la línea `# Fase 2` del CSV.
- `make_mapping.py apply` con la copia del CSV con los ámbitos ya renombrados: 119 + 74 + 72 + 83 =
  348 reemplazos.
- A mano, después: el `def` de las anidadas `_preguntar`→`_ask`, `registrar`→`record`,
  `falso`→`fake`, `con_marcas`→`with_marks`, `_espia`→`_spy` (×2), `input_and`→`op_y_entry` (decisión
  2 de la fase 1) y la clase `_Roto`→`_Broken`; los argnames de `parametrize`
  (`route_kwargs,autostart_on,start_ok,answers,remote`); 4 citas de docstring (`seen[1]`,
  `css_class == "warn"`, `[{sequence, inflight}]`, `_prepare_path`, `value`).
- **JS propio de `test_panel_estados`** (lo que dejó A8b), con `a9b/js6.py`: 71 tokens en las líneas
  de las cadenas JS, fuera de los literales JS con comilla simple (`'responde con error'` no se
  toca): `salida`→`emit`, `casos`→`testCases`, `cola`→`queue`, `con`/`sinLista` →
  `withList`/`withoutList`, `desdeCero`→`fromZero`, `estados`→`stateLog`, `fetchPendiente`→`fetchPending`,
  `filas`→`rowsOut`, `llamadas`→`callCount`, `respuestas`→`responses`, `retrasos`→`delays`,
  `ultima`/`vacio`/`vivo` → `lastHtml`/`emptyHtml`/`liveHtml`, `vistos`→`seenStates`, y las
  propiedades `c.secuencia`/`c.modelo` → `c.sequence`/`c.model`. Lecturas en Python: 14 `r["…"]` (no
  hay `.get`, `in`, `not in`, `pop` ni `{**…}` con esas claves) y 20 claves de los dicts de casos
  (`"secuencia"` ×19, `"modelo"` ×1).
- `except OSError: pass` de `test_precios.py:201` → `with contextlib.suppress(OSError):` con el mismo
  comentario (el fichero cambia de nombre), más `import contextlib`.
- `git mv` de 4 módulos: `test_dashboard_states.py`, `test_post_chat_paths.py`, `test_pricing.py` y
  `test_questions.py` (CRLF conservado: 368 `\r\n` = 368 `\n`).
- Comparadas por AST todas las cadenas antes y después: solo cambian el JS, los argnames, las citas,
  los nombres de tool MCP y las claves del test. Se quedan los datos: `"modelo"` como nombre de modelo
  en `server._post_chat("modelo", …)`, los ids de `parametrize` y los textos que afirman los tests.

### A9b-6 · Test nuevo de los esquemas de `elicitation`

`tests/test_questions.py::test_the_elicitation_schemas_keep_their_fields_and_visible_titles`,
parametrizado por formulario (3 tests): fija el `model_json_schema()` completo de `StartBackend`,
`ChooseModel` y `ChooseFormat`: los campos `start`/`model`/`format`, sus `title` visibles
(«Arrancar», «Modelo», «Formato»), los `title` de los formularios que conservó A8a-2 con `ConfigDict`
(«ArrancarBackend», «ElegirModelo», «ElegirFormato»), `description`, `required` y `type`. Mutante:
quitar `Field(title="Modelo")` hace fallar `[ChooseModel]` (tabla de controles).

### A9b-6 · Arreglo de la carrera

`test_turn_wait_shown_in_panel_as_local_wait` aceptaba la entrada de `/api/inflight` en cuanto traía
`turn_in_use`, pero `on_wait` (`server.py`) publica `turn_in_use` antes que `local_wait`: en esa
ventana la fila sale «procesando» y falla `row["text"] == "en cola local"` (el fallo que se vio una
vez en el CI de Ubuntu). La condición del bucle pasa a `queued and e and e.get("local_wait") and
e.get("turn_in_use")`, con un comentario que dice por qué. Lo que afirma el test no cambia. Control:
con un `time.sleep(0.5)` en esa ventana, el test viejo falla con `'procesando' == 'en cola local'` y
el arreglado pasa; 30 corridas seguidas del arreglado, bajo el cerrojo: 30 pasan.

### A9b-6 · Fuera del lote (consecuencia mecánica, aprobada)

- `src/local_delegate/server.py:1372` cita `tests/test_post_chat_paths.py` y
  `src/local_delegate/web/metrics.py:2522` cita `test_dashboard_states.py` (los dos CRLF, conservado).

### A9b-6 · Barrido final

- AST de los 4 ficheros: ningún nombre de código, kwarg, argname ni cita con un `old` del lote.
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 166 en
  textos (75 docstrings, 46 comentarios y 45 cadenas): prosa y datos en español.
- En todo el repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`), los nombres propios del lote: 0.
- `--collect-only`: **2572** = 2569 + 3 del test nuevo (`evidence/A9b-6/collect.txt`). Suite (con
  Playwright, bajo el cerrojo): 2570 passed, 2 skipped (`evidence/A9b-6/pytest-full.log`). `ruff
  check` y `ruff format --check` en verde.
- CodeQL (aproximación AST) sobre los 4 ficheros renombrados: 0 patrones.

### A9b-6 · Desviaciones

1. **9 filas `pycharm` → `search_edit`**, anotado en la línea `# Fase 2` del CSV: 7 parámetros
   homónimos y los 2 campos `valor`.
2. **Las cadenas de nombre de tool MCP** (`"probar"`, `"responder_opcional"`) no estaban en el CSV:
   cambian con la función por consecuencia (lección de A9a) y se anotan en la misma línea.
3. **`contextlib.suppress`** en vez de `except OSError: pass` en `test_pricing.py`, como en el lote 5.

## Cierre de A9b

- **Barrido de los 6 mappings** sobre los ficheros con su nombre final (AST de nombres, kwargs,
  argnames y cadenas iguales a un `old`): 0 en código en los 24 ficheros. Las cadenas iguales a un
  `old` que quedan son datos: `"viejo"`/`"nuevo"` (formato de `_read_rows`), `"bloqueo"`/`"codigo"`
  (telemetría vieja), `"secreto"` y `"antes"` (datos de prueba) en el lote 3; `"modelo"` (valor viejo
  de `fallback_class` y nombre de modelo de prueba), `"fallos"`/`"hasta"` (fichero viejo de
  enfriamiento), `"coletilla"`/`"recibo"` (etiquetas de mensaje) y `"tokens_aprox"` (clave del
  producto) en los lotes 5 y 6.
- **Detector** (`scripts/detect_spanish_names.py --json`, filtrado a los ficheros de A9b y
  `tests/fixtures/backend`): 159 hallazgos, ninguno es un nombre de Python del test salvo los dos
  `test_*` que nombran el script retirado `anotar_llamada` (dato: es el nombre del fichero viejo que
  el test comprueba que se retira) y `bloqueo_id`/`secciones`/`fallo_conexion` (kwargs con claves
  viejas que el test mete a propósito para comprobar la lectura de logs antiguos). El resto son
  cadenas: 107 valores (nombres de fichero de prueba como `informe.md` o `casos.json`, valores
  viejos persistidos, ids de `parametrize`) y 47 claves, de cuatro clases:
  - del producto o de scripts (A10 / sin ola): `modelo`/`tamano_bytes`/`ruta` de la huella de
    `footprint` (`test_footprint.py`), las del informe de `scripts/measure_slowness.py`
    (`test_measure_slowness.py`: `cumple`, `faltan`, `eventos_pc`…), `desconocido`, `pruebas`;
  - viejas a propósito: `fallos`, `espera_s`, `hasta`, `LD_HOOK_READ_BLOQUEAR`, `mcp_ajeno`;
  - etiquetas de mensaje del test: `coletilla`, `recibo`, `_ensayo`/`_otra`, `viva`, `otro`/`cosa`/`otra`/`proyecto`/`ajeno`;
  - **claves propias de los tests de llama-swap que el mapping no cubría**: `recargando`/`recargada`/
    `rechazo` (`fake_llamaswap._count`) y `durante`/`t_descarga`/`cargado_a_los_4s`/`estado`/`duracion`
    (`test_fake_llamaswap.py`). Ver pendiente 3.
- **Conteo final**: 2572 tests recogidos = 2569 + 3 (el test nuevo de esquemas, parametrizado).
- **Mappings**: 1507 filas en 6 lotes; 151 `rename_refactoring`; 0 discrepancias en
  `check_wave_records.py`.

## Pendientes

Lo que A9b deja a otras olas, por destino:

**A9c (`q*`–`z*`)**
1. `test_fallback_observability.py` importa de `test_respaldo.py` `_enfriar`, `_ultimo_evento`,
   `CODIGO`, `LARGO` y `MECANICO`; no se tocaron aquí. Cuando A9c los renombre, cambia ese import como
   consecuencia mecánica. `_textos` de `test_recalcular.py` es un homónimo sin relación.
2. Lecciones para A9c: buscar las claves en todas sus formas (`["x"]`, `.get("x")`, `"x" in`,
   `"x" not in`, `pop`, `{**…}`) y comprobar con un mutante los asserts negativos de claves
   renombradas (lote 1); barrer los parámetros de lambdas (lote 2); los nombres de tool MCP cambian con
   la función (lote 6).

**Sin ola (decide la sesión principal)**
3. Las claves propias de los tests de llama-swap que el mapping no cubrió (`fake_llamaswap._count`:
   `recargando`/`recargada`/`rechazo`; `test_fake_llamaswap.py`: `durante`, `t_descarga`,
   `cargado_a_los_4s`, `estado`, `duracion`). Son del test, no persistidas: propuesta, un lote corto o
   A9c, con su barrido de lecturas.

**A10 (scripts) y producto**
4. Las claves del informe de `scripts/measure_slowness.py` que lee `test_measure_slowness.py`, y las
   de `footprint` (`modelo`, `tamano_bytes`, `ruta`) que lee `test_footprint.py`: cambian con el
   script o con su decisión de lectura dual, no en los tests.

**Intermitentes abiertos** (no son de A9b)
5. `test_fake_llamaswap.py::test_a_ttl_counts_from_request_end` (`t_unload` 4,23 > 4,0) y
   `::test_d_8_s_request_in_progress_on_reload[cambio_ajeno]` (500 en vez de 502), los dos bajo la
   carga de `-n auto` en la primera corrida del lote 1.
6. `test_residency_cli.py::test_restoring_a_copy_end_to_end` (visto en A9a).

La carrera de `test_turn_wait_shown_in_panel_as_local_wait` queda **cerrada** en el lote 6.
