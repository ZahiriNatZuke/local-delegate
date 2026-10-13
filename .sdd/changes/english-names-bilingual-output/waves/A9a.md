# Ola A9a — Tests `conftest.py`, fixtures de datos y módulos `a*`–`d*`

La subola se parte en 7 lotes (D13: 1788 filas, máximo 300 por lote y sin partir un módulo, salvo
la excepción aprobada del JS de `test_dashboard_ui.py`, que va al lote 7). Cada lote es un commit
que hace la sesión principal, en una rama apilada sobre el anterior. Los **lotes 1 y 2** están en `main`
(`2860497`, PR #272; `b10b468`, PR #273); el **lote 3** en `a6069f8` (PR #274), con el arreglo de
CodeQL `2809dd1`; el **lote 4** en `d525e3f`; el **lote 5** en `fcc6dba`; el **lote 6** en `0dcd0cb`. El **lote 7**, el
último, está aplicado y registrado en la sección «A9a-7», y el **cierre de la subola** en «Cierre de
A9a», al final. Las tablas de controles positivos, `local_*` y PyCharm son las de los siete lotes,
porque `check_wave_records.py` lee la primera tabla de cada sección: 37 + 21 + 21 + 18 + 32 + 34 + 11
= 174 filas `rename_refactoring` = 174 filas `pycharm` de los mappings A9a-1 a A9a-7.

- Rama: lote 1 en `sdd/english-names-a9a`, desde `main` en `f4a869f` (A8b mezclada), commit `799562a` (PR #272); lote 2 en `sdd/english-names-a9a-2`, commit `584845c` (PR #273), rebasado sobre `main` con el lote 1 (`2860497`); lote 3 en `sdd/english-names-a9a-3`, commit `a6069f8` (PR #274), rebasado sobre `main`; lote 4 en `sdd/english-names-a9a-4`, commit `d525e3f`, sobre `2809dd1` (arreglo de CodeQL de la sesión principal); lote 5 en `sdd/english-names-a9a-5`, commit `fcc6dba`; lote 6 en `sdd/english-names-a9a-6`, commit `0dcd0cb`; lote 7 en `sdd/english-names-a9a-7`, apilada sobre `0dcd0cb` · Commit del lote 7: pendiente, con el borrador en `waves/A9a-7-commit-msg.txt` (firmado y sin coautoría)
- Quién: un agente hizo los 7 mappings (fase 1). Tras la aprobación de la sesión principal (decisiones 1-8, con `esp`→`expected` y `clase`→`css_class`/`cls`/`content_class` según lo que nombre), el mismo agente aplicó el lote 1 (fase 2)
- REQ cubiertos por el lote 1: REQ-015 (nombres de `tests/conftest.py`, `tests/backend_mock.py`, `test_agents.py`, `test_aislamiento_entorno.py`→`test_environment_isolation.py` y `test_atribucion.py`→`test_attribution.py`, más los directorios de fixtures `residencia`→`residency` y `topologia`→`topology`) y REQ-017 (ningún assert cambia de sentido)
- Ficheros poseídos por el lote 1: `tests/conftest.py`, `tests/backend_mock.py`, `tests/test_agents.py`, `tests/test_aislamiento_entorno.py`, `tests/test_atribucion.py` y `tests/fixtures/{residencia,topologia}/`. Lo de fuera, en «Desviaciones»
- EOL: `evidence/A9a-1/eol-check.txt` (EOL de HEAD frente al de trabajo en cada fichero del diff, con los renombres seguidos): 0 diferencias. Todo LF salvo `residency/pre-b10909-20260915.yaml`, que sigue `mixed` y con `-text` en `.gitattributes`. Todas las ediciones desde fuera, con Python y `newline=""`
- Mapping: `waves/A9a-1-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 294 filas. Filas `pycharm` 37 = filas `rename_refactoring` 37. Filas `search_edit` 257, cada una con su motivo: 239 con `make_mapping.py apply` (601 reemplazos; más el `def` de 10 anidadas con `a9a/nested_defs.py`), 12 parámetros y atributos homónimos pasados de `pycharm` a `search_edit` en la fase 2 (`a9a/lineedit.py`), 2 módulos y 4 directorios o ficheros de fixtures con `git mv`
- Tests recogidos: antes 2567 (`evidence/A9a/collect-before.txt`) → después 2567 (`evidence/A9a-1/collect.txt`), +0 −0. Por fichero, iguales: `test_atribucion.py` 33 → `test_attribution.py` 33 y `test_aislamiento_entorno.py` 5 → `test_environment_isolation.py` 5
- Suite: `evidence/A9a-1/pytest-full.log` (`pytest -q -n auto --dist loadgroup` como el CI, con `pesado.sh`), verde: 2565 pasan, 2 saltados y el aviso ya conocido de Starlette (`BlockingPortal`, 12 veces, una por worker), en 59 s. Una corrida anterior (`pytest-full-run2-flaky.log`) dio 1 fallo en `test_dashboard_ui.py::test_la_unidad_de_los_kpis_no_se_corta[ancha]`, que no toca este lote: suelto pasó 3 de 3, y la corrida siguiente salió entera en verde
- `ruff check` y `ruff format --check` sobre `src tests scripts .sdd/changes/english-names-bilingual-output/tools`: limpios (`evidence/A9a-1/ruff-check.txt`, 187 ficheros). `ruff format` reajustó 4 ficheros a los que el rename cambió el largo de línea (`test_agents.py`, `test_attribution.py`, `test_observabilidad_respaldo.py`, `test_rol_fast_retirado.py`); esos 4 se volvieron a pasar después (73 pasan)
- Tamaño: 28 ficheros, +824 −813 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`). `test_atribucion.py`→`test_attribution.py` queda en el 46 % de similitud: git solo lo sigue como rename con `-M30%` (`git log --follow -M30%`)

## Controles positivos

| Test | Mutante aplicado | Assert que disparó | Restaurado |
| --- | --- | --- | --- |
| `tests/test_attribution.py::test_does_not_read_more_than_256_kb` (usa los renombrados `_ReadSpy`, `.reads`, `_stream`, `_spy`, `_projects`, `_write_note`, `_tool_use_line`) | `src/local_delegate/attribution.py`: `TAIL_BYTES = 256 * 1024` → `512 * 1024` (sha256 `32d9a7febbed` → `9d774322a27d`: el mutante muta) | `tests/test_attribution.py:383` `assert spy.reads <= 256 * 1024` → `assert 524288 <= (256 * 1024)`; la guarda `spy.reads > 0` de :382 pasa, así que el test llegó a leer (`evidence/A9a-1/mutant.txt`) | sí: `git checkout` devolvió la versión de HEAD y se repuso la cita de :17 de la ola; sha256 `32d9a7febbed`, igual que antes del mutante |
| `tests/test_benchmark.py::test_voided_run_is_repeated_with_the_same_tokens` y `::test_the_voided_run_is_repeated_at_most_twice` (lote 2; usan los renombrados `_VoidingProbe`, `.reasons`, `_run`, `_response`) | `src/local_delegate/benchmark.py:1340`: `annul_retries < MAX_ANNUL_RETRIES` → `annul_retries < 0`, sin reintentos (sha256 `4b1593fcf3a5` → `3ca7cad98f5c`) | `test_benchmark.py:565` `assert seen == [16, 16]` → `[16] == [16, 16]`; `:575` `assert len(records) == 1 + benchmark.MAX_ANNUL_RETRIES` → `1 == (1 + 2)` (`evidence/A9a-2/mutant.txt`) | sí, desde una copia guardada antes de mutar: sha256 `4b1593fcf3a5` |
| `tests/test_connection_cause.py::test_each_event_has_its_cause` (lote 3; usa los renombrados `_CASES`, `_wrapped`, `factory`, `expected` y la cadena de `parametrize`) | `src/local_delegate/failures.py:318`: `return ConnectionCause.REFUSED` → `DNS` (sha256 `c8e2e0e55c7a` → `d0de925733bb`) | `test_connection_cause.py:173` `assert cause is expected` → `<ConnectionCause.DNS> is <ConnectionCause.REFUSED>`; 1 falla y 27 pasan (`evidence/A9a-3/mutant.txt`, M1) | sí, desde copia: `c8e2e0e55c7a` |
| `tests/test_checks.py::test_an_http_entry_without_header_is_reported_as_blind_not_as_a_missing_variable` (test NUEVO del lote 3) | `checks.py:1124`: `_entry_auth` devuelve `"sin_credencial"` y no `"no_credential"` (el mutante M1 del hallazgo de A8a-1; sha256 `6766bd49328a` → `e4f821dfab58`) | `test_checks.py:1275` `assert "sin cabecera de autorización" in result.detail` → el detalle es el de la rama «variable que no está»; también falla el otro test nuevo (:1286). El test viejo `…against_a_daemon_with_token_warns` sigue pasando: no distingue, como decía el hallazgo (M2a) | sí, desde copia: `6766bd49328a` |
| `tests/test_checks.py::test_an_http_entry_without_credential_is_tagged_no_credential` (test NUEVO del lote 3) | `checks.py`: los 4 `"no_credential"` → `"sin_credencial"`, con lo que el probe queda coherente (sha256 `6766bd49328a` → `a7d3cedbcf2b`) | `test_checks.py:1286` `assert checks._entry_auth(client, "http", None) == (client, "no_credential")` → `'sin_credencial' != 'no_credential'`; los otros dos pasan (M2b) | sí, desde copia: `6766bd49328a` |
| `tests/test_ci_gate.py::test_waits_for_the_missing_ones_and_then_passes` (lote 4; usa los renombrados `_Clock.sleep`, `_run(read, clock)` y `_all`) | `scripts/ci_gate.py:277`: `dormir(INTERVALO_S)` → `dormir(2 * INTERVALO_S)` (sha256 `877a25dae814` → `895b50d8bdae`) | `test_ci_gate.py:242` `assert clock.t == ci_gate.INTERVALO_S` → `assert 20.0 == 10`; el otro test del bucle pasa (`evidence/A9a-4/mutant.txt`) | sí, desde copia: `877a25dae814` |
| `tests/test_density.py::test_the_tool_wins_over_the_extension` (lote 5; usa la variable renombrada `content_class` y el módulo `test_densidad`→`test_density`) | `src/local_delegate/cost.py:101`: `if by_tool:` → `if by_tool and not event.get("path"):`, con lo que la extensión gana a la tool (sha256 `412e2b7e8c16` → `86576b81627a`) | `test_density.py:117` `assert content_class == "log"` → `'code' == 'log'` (`evidence/A9a-5/mutant.txt`) | sí, desde copia: `412e2b7e8c16` |
| `tests/test_doctor.py::test_backend_probe_uses_the_probe_timeout` (lote 6; usa la anidada renombrada `_Recorder`) | `src/local_delegate/probes.py:279`: `connect=config.PROBE_CONNECT_TIMEOUT` → `connect=config.PROBE_READ_TIMEOUT` (sha256 `69ca3701f83a` → `a1c77e14a87b`) | `test_doctor.py:406` `assert connect_timeout == config.PROBE_CONNECT_TIMEOUT` → `assert 2.0 == 3.0` (`evidence/A9a-6/mutant.txt`) | sí, desde copia: `69ca3701f83a` |
| `tests/test_dashboard_js.py::test_the_previous_month_goes_from_day_1_to_day_1` (lote 7; usa las claves JS renombradas `startDay`/`endDay` y sus lecturas Python) | `src/local_delegate/web/metrics.py:1781` (`computeRange('prev-month')`): `to:new Date(y, m, 1)` → `to:new Date(y, m, 2)` (sha256 `1840a42ecfe1` → `90c4dd5859c8`) | `test_dashboard_js.py:161` `assert (result["startDay"], result["endDay"]) == (1, 1)` → `(1, 2) == (1, 1)` (`evidence/A9a-7/mutant.txt`) | sí, desde copia: `1840a42ecfe1` |

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A9a-1 | `local_lint_summary(path=evidence/A9a-1/pytest-full.log)` | resumen de la suite | útil: solo los 12 avisos de `BlockingPortal` de Starlette, ningún fallo |
| agente A9a-2 | `local_lint_summary(path=evidence/A9a-2/pytest-full.log)` | resumen de la suite del lote 2 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-3 | `local_lint_summary(path=evidence/A9a-3/pytest-full.log)` | resumen de la suite del lote 3 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-4 | `local_lint_summary(path=evidence/A9a-4/pytest-full.log)` | resumen de la suite del lote 4 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-5 | `local_lint_summary(path=evidence/A9a-5/pytest-full.log)` | resumen de la suite del lote 5 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-6 | `local_lint_summary(path=evidence/A9a-6/pytest-full.log)` | resumen de la suite del lote 6 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-6 | `local_lint_summary(path=evidence/A9a-6/playwright.log)` | resumen de Playwright entero (`test_dashboard_ui`, `test_panel_estados`, `test_panel_coste`) | útil: 0 errores en los tres, solo el aviso de Starlette |
| agente A9a-7 | `local_lint_summary(path=evidence/A9a-7/pytest-full-run1-parametrize.log)` | primera corrida de la suite del lote 7 | útil: 12 errores de colección de `test_dashboard_js.py` («function uses no argument 'incluir'») y 1 fallo de `test_residency_cli.py`; corregido (ver «A9a-7 · Qué se hizo») |
| agente A9a-7 | `local_lint_summary(path=evidence/A9a-7/pytest-full.log)` | suite del lote 7, segunda corrida | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |

Fase 1 (mappings): 0 llamadas, porque hacían falta líneas literales (contexto de cada nombre, reglas del brief) y las listas largas fueron a ficheros del scratchpad, leídos por franjas.

## Llamadas `mcp__pycharm__*`

| Quién | Tool | Símbolo o patrón | Resultado |
| --- | --- | --- | --- |
| agente A9a-1 | `rename_refactoring` | `conftest.recargar_config` → `reload_config` | 222 usos; tocó también 4 docs de `.sdd/` (devueltos con `git checkout`) |
| agente A9a-1 | `rename_refactoring` | `conftest.entorno_sin_variables_del_paquete` → `env_without_package_variables` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `conftest.sin_lista_de_modelos_guardada` → `no_saved_model_list` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._rutas` → `_routes` | 8 usos (también `test_cadenas.py:279`) |
| agente A9a-1 | `rename_refactoring` | `backend_mock._Llamadas` → `_Calls` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._Llamada` → `_Call` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta` → `Route` | 6 usos |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta._coincide` → `_matches` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock.Ruta._resolver` → `_resolve` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `backend_mock._activo` → `_active` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.ANCLA` → `ANCHOR` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.AJENO` → `FOREIGN` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.SIN_SECCION` → `NO_SECTION` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `test_agents.DELEGADOR` → `DELEGATOR` | 9 usos |
| agente A9a-1 | `rename_refactoring` | `_nombre_de_llamada` → `_call_name` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_variables_que_leen_los_hooks` → `_variables_read_by_hooks` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `con_alias` → `with_alias` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `AGENTE` → `AGENT` | 6 usos |
| agente A9a-1 | `rename_refactoring` | `_entorno_del_hook` → `_hook_env` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_lanzar_hook` → `_launch_hook` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_dir_notas` → `_notes_dir` | 3 usos |
| agente A9a-1 | `rename_refactoring` | `_entrada_hook` → `_hook_input` | 5 usos |
| agente A9a-1 | `rename_refactoring` | `_linea_tool_use` → `_tool_use_line` | 14 usos |
| agente A9a-1 | `rename_refactoring` | `_proyectos` → `_projects` | 9 usos |
| agente A9a-1 | `rename_refactoring` | `_escribir` → `_write` | 11 usos |
| agente A9a-1 | `rename_refactoring` | `_anotar` → `_write_note` | 17 usos |
| agente A9a-1 | `rename_refactoring` | `_Contador` → `_Counter` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `_EspiaDeLectura` → `_ReadSpy` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `log_y_notas` → `log_and_notes` | 0 usos (los parámetros ya los había renombrado `apply`) |
| agente A9a-1 | `rename_refactoring` | `_lineas` → `_lines` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `_log_minimo` → `_minimal_log` | 4 usos |
| agente A9a-1 | `rename_refactoring` | `_en_peticion` → `_in_request` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_Espia` → `_Spy` | 1 uso |
| agente A9a-1 | `rename_refactoring` | `_peticiones` → `_requests` | 2 usos |
| agente A9a-1 | `rename_refactoring` | `_relleno_viejo` → `_old_backfill` | 7 usos |
| agente A9a-1 | `rename_refactoring` | `ENTRADAS_VIEJAS` → `OLD_ENTRIES` | 8 usos |
| agente A9a-1 | `rename_refactoring` | `_temporal` → `_tmp_dir` | 3 usos |
| agente A9a-1 | `get_file_problems` | `tests/test_attribution.py`, `tests/backend_mock.py`, `tests/conftest.py` (solo errores) | 0 errores |
| agente A9a-2 | `rename_refactoring` | `test_benchmark.RAIZ` → `ROOT` | 5 usos |
| agente A9a-2 | `rename_refactoring` | `_COMPONENTES_POR_SENAL` → `_COMPONENTS_BY_SIGNAL` | 2 usos |
| agente A9a-2 | `rename_refactoring` | `test_benchmark._correr` → `_run` | 13 usos |
| agente A9a-2 | `rename_refactoring` | `_respuesta` → `_response` | 11 usos |
| agente A9a-2 | `rename_refactoring` | `_SondaQueAnula` → `_VoidingProbe` | 4 usos |
| agente A9a-2 | `rename_refactoring` | `_responde` → `_reply` | 17 usos |
| agente A9a-2 | `rename_refactoring` | `MECANICO` → `MECHANICAL` | 15 usos |
| agente A9a-2 | `rename_refactoring` | `LARGO` → `LONG` | 28 usos |
| agente A9a-2 | `rename_refactoring` | `CODIGO` → `CODE` | 17 usos |
| agente A9a-2 | `rename_refactoring` | `RETIRADO` → `RETIRED` | 3 usos |
| agente A9a-2 | `rename_refactoring` | `CAPACIDAD` → `CAPACITY_ERROR` | 2 usos |
| agente A9a-2 | `rename_refactoring` | `HOY` → `TODAY` | 2 usos |
| agente A9a-2 | `rename_refactoring` | `_fallo` → `_failure` | 8 usos |
| agente A9a-2 | `rename_refactoring` | `_texto` → `_text` | 1 uso |
| agente A9a-2 | `rename_refactoring` | `test_captura.RAIZ` → `ROOT` | 9 usos |
| agente A9a-2 | `rename_refactoring` | `CAPTURA` → `SCREENSHOT` | 5 usos |
| agente A9a-2 | `rename_refactoring` | `MANIFIESTO` → `MANIFEST` | 4 usos |
| agente A9a-2 | `rename_refactoring` | `PASAN_AL_SERVIDOR_REAL` → `PASS_TO_REAL_SERVER` | 2 usos |
| agente A9a-2 | `rename_refactoring` | `REGENERAR` → `REGENERATE` | 4 usos |
| agente A9a-2 | `rename_refactoring` | `_manifiesto` → `_manifest` | 3 usos |
| agente A9a-2 | `rename_refactoring` | `_version_declarada` → `_declared_version` | 1 uso |
| agente A9a-2 | `get_file_problems` | `tests/test_benchmark.py`, `tests/test_chains.py`, `tests/test_capture.py` (solo errores) | 0 errores nuevos: el único, `Unresolved reference 'yaml'` en `test_chains.py:124` (`monkeypatch.setattr(topology, "yaml", None)`), ya estaba en HEAD |
| agente A9a-3 | `rename_refactoring` | `_PETICION` → `_REQUEST` | 3 usos |
| agente A9a-3 | `rename_refactoring` | `_envuelta` → `_wrapped` | 15 usos |
| agente A9a-3 | `rename_refactoring` | `_Propia` → `_OwnError` | 1 uso |
| agente A9a-3 | `rename_refactoring` | `_CASOS` → `_CASES` | 2 usos |
| agente A9a-3 | `rename_refactoring` | `_clasifica_en_un_hilo` → `_classify_in_a_thread` | 2 usos |
| agente A9a-3 | `rename_refactoring` | `_fallo_real` → `_real_failure` | 3 usos |
| agente A9a-3 | `rename_refactoring` | `_puerto_recien_liberado` → `_just_freed_port` | 1 uso |
| agente A9a-3 | `rename_refactoring` | `_sin_el_arranque_remoto` → `_without_remote_start` | 1 uso |
| agente A9a-3 | `rename_refactoring` | `_DETALLES` → `_DETAILS` | 2 usos |
| agente A9a-3 | `rename_refactoring` | `_ETIQUETAS` → `_LABELS` | 5 usos |
| agente A9a-3 | `rename_refactoring` | `_publicada` → `_published` | 9 usos |
| agente A9a-3 | `rename_refactoring` | `_con_huerfanos` → `_with_orphans` | 2 usos |
| agente A9a-3 | `rename_refactoring` | `observando` → `observing` | 9 usos |
| agente A9a-3 | `rename_refactoring` | `_NUMERO_SIN_SUSTANTIVO` → `_NUMBER_WORDS_WITHOUT_NOUN` | 4 usos |
| agente A9a-3 | `rename_refactoring` | `_NUMERO` → `_NUMBER_WORDS` | 3 usos |
| agente A9a-3 | `rename_refactoring` | `_home_con_credencial` → `_home_with_credential` | 4 usos |
| agente A9a-3 | `rename_refactoring` | `_probe_ventanas` → `_probe_windows` | 5 usos |
| agente A9a-3 | `rename_refactoring` | `_con_stdio` → `_with_stdio` | 4 usos |
| agente A9a-3 | `rename_refactoring` | `_ctx_con_daemon` → `_ctx_with_daemon` | 4 usos |
| agente A9a-3 | `rename_refactoring` | `_con_desktop` → `_with_desktop` | 13 usos |
| agente A9a-3 | `rename_refactoring` | `_sin_token` → `_without_token` | 3 usos |
| agente A9a-3 | `get_file_problems` | `tests/test_checks.py`, `tests/test_connection_cause.py`, `tests/test_chunking.py` (solo errores) | 0 errores |
| agente A9a-4 | `rename_refactoring` | `PASOS_COMPLETOS` → `COMPLETE_STEPS` | 3 usos |
| agente A9a-4 | `rename_refactoring` | `_Reloj` → `_Clock` | 3 usos |
| agente A9a-4 | `rename_refactoring` | `_todos` → `_all` | 2 usos |
| agente A9a-4 | `rename_refactoring` | `test_ci_gate._correr` → `_run` | 6 usos |
| agente A9a-4 | `rename_refactoring` | `_jobs_declarados_en_ci` → `_jobs_declared_in_ci` | 2 usos |
| agente A9a-4 | `rename_refactoring` | `GRACIA_GITHUB` → `GITHUB_GRACE` | 3 usos |
| agente A9a-4 | `rename_refactoring` | `registro_limpio` → `clean_registry` | 0 usos (autouse o parámetros ya editados) |
| agente A9a-4 | `rename_refactoring` | `test_clients._lineas` → `_lines` | 8 usos |
| agente A9a-4 | `rename_refactoring` | `_conversar` → `_converse` | 7 usos |
| agente A9a-4 | `rename_refactoring` | `_firmar` → `_sign` | 4 usos |
| agente A9a-4 | `rename_refactoring` | `_tool_use_id_visto` → `_seen_tool_use_id` | 3 usos |
| agente A9a-4 | `rename_refactoring` | `entorno (fixture)` → `hook_env` | 0 usos (autouse o parámetros ya editados) |
| agente A9a-4 | `rename_refactoring` | `test_conformidad_f1._eventos` → `_events` | 5 usos |
| agente A9a-4 | `rename_refactoring` | `test_conformidad_f1._correr` → `_run` | 16 usos |
| agente A9a-4 | `rename_refactoring` | `_prosa` → `_prose` | 12 usos |
| agente A9a-4 | `rename_refactoring` | `_enfriar` → `_cool_down` | 5 usos |
| agente A9a-4 | `rename_refactoring` | `notas (fixture)` → `notes` | 0 usos (autouse o parámetros ya editados) |
| agente A9a-4 | `rename_refactoring` | `test_correlacion._eventos` → `_events` | 2 usos |
| agente A9a-4 | `get_file_problems` | `tests/test_ci_gate.py`, `tests/test_clients.py`, `tests/test_f1_conformance.py` (solo errores) | 0 errores nuevos: los 2 de `test_f1_conformance.py:60-61` (`Unresolved reference 'backend_available'` en `monkeypatch.setattr(read_hook, …)`, módulos cargados con `importlib`) ya estaban en HEAD |
| agente A9a-5 | `rename_refactoring` | `_cotejo` → `_crosscheck` | 5 usos |
| agente A9a-5 | `rename_refactoring` | `_sin_web_ni_arranques` → `_without_web_or_starts` | 0 usos (fixture: autouse o parámetros ya editados por `apply`) |
| agente A9a-5 | `rename_refactoring` | `_interrumpir` → `_interrupt` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `solo_windows` → `windows_only` | 3 usos |
| agente A9a-5 | `rename_refactoring` | `_entorno_aislado` → `_isolated_env` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `_lanzar` → `_launch` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `_romper_y_esperar` → `_break_and_wait` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `fila` → `row` | 21 usos |
| agente A9a-5 | `rename_refactoring` | `test_cuota._lineas` → `_lines` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `puntos_de` → `points_of` | 7 usos |
| agente A9a-5 | `rename_refactoring` | `_punto` → `_point` | 7 usos |
| agente A9a-5 | `rename_refactoring` | `_RespuestaFalsa` → `_FakeResponse` | 1 uso |
| agente A9a-5 | `rename_refactoring` | `_doblar_get_crudo` → `_stub_get_raw` | 10 usos |
| agente A9a-5 | `rename_refactoring` | `_doblar_get` → `_stub_get` | 6 usos |
| agente A9a-5 | `rename_refactoring` | `_RespuestaHTTP` → `_HTTPResponse` | 8 usos |
| agente A9a-5 | `rename_refactoring` | `_plazo_conexion` → `_connect_timeout` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `cliente_nuevo` → `new_client` | 0 usos (fixture: autouse o parámetros ya editados por `apply`) |
| agente A9a-5 | `rename_refactoring` | `registradores` → `recorders` | 0 usos (fixture: autouse o parámetros ya editados por `apply`) |
| agente A9a-5 | `rename_refactoring` | `_ultima_linea_del_log` → `_last_log_line` | 3 usos |
| agente A9a-5 | `rename_refactoring` | `_png_minimo` → `_minimal_png` | 1 uso |
| agente A9a-5 | `rename_refactoring` | `_troceada_map_reduce` → `_chunked_map_reduce` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `_troceada_por_trozos` → `_chunked_by_chunks` | 1 uso |
| agente A9a-5 | `rename_refactoring` | `_imagen` → `_image` | 1 uso |
| agente A9a-5 | `rename_refactoring` | `_entrada_inflight` → `_inflight_entry` | 5 usos |
| agente A9a-5 | `rename_refactoring` | `_esperar` → `_wait` | 2 usos |
| agente A9a-5 | `rename_refactoring` | `_respaldo_declarado` → `_declared_fallback` | 0 usos (fixture: autouse o parámetros ya editados por `apply`) |
| agente A9a-5 | `rename_refactoring` | `_fila` → `_row` | 17 usos |
| agente A9a-5 | `rename_refactoring` | `_extraer_funcion_js` → `_extract_js_function` | 5 usos |
| agente A9a-5 | `rename_refactoring` | `DE_LA_LINEA` → `MODEL_FROM_LINE` | 4 usos |
| agente A9a-5 | `rename_refactoring` | `DEL_RELLENO` → `MODEL_FROM_BACKFILL` | 6 usos |
| agente A9a-5 | `rename_refactoring` | `_bloque_de_tokens_aprox` → `_approx_tokens_block` | 1 uso |
| agente A9a-5 | `rename_refactoring` | `_acct_en_js` → `_acct_in_js` | 4 usos |
| agente A9a-5 | `get_file_problems` | `tests/test_quota.py`, `tests/test_daemon.py`, `tests/test_density.py` (solo errores) | 0 errores nuevos: los 3 de `test_daemon.py` (`Unresolved reference 'Server'` en `monkeypatch.setattr(daemon.uvicorn, "Server", …)`) ya estaban en HEAD |
| agente A9a-6 | `rename_refactoring` | `_tam_pagina` → `_page_size` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_eventos` → `_events` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_Servidor` → `_Server` | 16 usos |
| agente A9a-6 | `rename_refactoring` | `_navegador` → `_browser` | 16 usos |
| agente A9a-6 | `rename_refactoring` | `_filas_visibles` → `_visible_rows` | 3 usos |
| agente A9a-6 | `rename_refactoring` | `_CHARS_DEVUELTOS` → `_CHARS_RETURNED` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_CHARS_LEIDOS` → `_CHARS_READ` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_BRUTO` → `_GROSS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_DEVUELTO` → `_RETURNED` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_NETO` → `_NET` | 3 usos |
| agente A9a-6 | `rename_refactoring` | `_PROCESO` → `_PROCESS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_MEDIR_TARJETAS` → `_MEASURE_CARDS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_MEDIR` → `_MEASURE` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_log_presentacion` → `_showcase_log` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `medidas` → `measurements` | 0 usos (fixture: los parámetros ya los había renombrado `apply`) |
| agente A9a-6 | `rename_refactoring` | `_SISTEMA_ESTADOS` → `_SYSTEM_STATES` | 5 usos |
| agente A9a-6 | `rename_refactoring` | `_TIPOGRAFIA_TARJETAS` → `_CARD_TYPOGRAPHY` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_log_coste_e_imagen` → `_cost_and_image_log` | 11 usos |
| agente A9a-6 | `rename_refactoring` | `FUENTES` → `FONT_STATES` | 4 usos |
| agente A9a-6 | `rename_refactoring` | `_FUENTE_ANCHA` → `_WIDE_FONT` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_INTER_CARGADA` → `_INTER_LOADED` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_antes_de_cargar` → `_before_loading` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_tras_cargar` → `_after_loading` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_DESBORDES_KPI` → `_KPI_OVERFLOWS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_HOOKS_CRUDOS` → `_RAW_HOOKS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_SISTEMA` → `_SYSTEM` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_clientes_crudos` → `_raw_clients` | 1 uso |
| agente A9a-6 | `rename_refactoring` | `_pagina_completa` → `_full_page` | 6 usos |
| agente A9a-6 | `rename_refactoring` | `_PRIMERAS_COLUMNAS` → `_FIRST_COLUMNS` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_TIPOGRAFIA_TABLAS` → `_TABLE_TYPOGRAPHY` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_SIMETRIA_KPIS` → `_KPI_SYMMETRY` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_DECIMAL_CON_PUNTO` → `_DECIMAL_WITH_DOT` | 3 usos |
| agente A9a-6 | `rename_refactoring` | `_SPARK_Y_PISTA` → `_SPARK_AND_HINT` | 2 usos |
| agente A9a-6 | `rename_refactoring` | `_miles` → `_thousands` | 4 usos |
| agente A9a-6 | `get_file_problems` | `tests/test_dashboard_ui.py`, `tests/test_doctor.py` (solo errores) | 0 errores nuevos: el de `test_doctor.py:399` (`Unresolved reference 'Client'` en `monkeypatch.setattr(httpx2, "Client", …)`) ya estaba en HEAD |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js.TZ_PRUEBA` → `TEST_TZ` | 2 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._extraer` → `_extract` | 9 usos (también el import de `test_panel_estados.py`) |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._correr` → `_run` | 22 usos (también el import de `test_panel_estados.py`) |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._DOM_FECHAS` → `_DATES_DOM` | 6 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._TEXTO_PRUEBAS` → `_TESTS_TEXT` | 3 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._PRELUDIO_FETCH` → `_PRELUDE_FETCH` | 2 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._PRELUDIO_F` → `_PRELUDE_F` | 2 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._texto_pruebas` → `_tests_text` | 5 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._legado` → `_legacy` | 1 uso |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._SIN_INTL_V3` → `_WITHOUT_INTL_V3` | 4 usos |
| agente A9a-7 | `rename_refactoring` | `test_dashboard_js._formateadores` → `_formatters` | 8 usos (también el import de `test_panel_estados.py`) |
| agente A9a-7 | `get_file_problems` | `tests/test_dashboard_js.py`, `tests/test_dashboard_ui.py`, `tests/test_panel_estados.py` (solo errores) | 0 errores |

## Revisión del diff tras rename_refactoring

- PyCharm reescribió documentos de `.sdd/` (`daemon-reparte-el-backend/evidencias/renombrado.md`, `delegacion-precisa-y-fiable/plan.md` y `verification.md`, `english-names-bilingual-output/research-rename.md`, `review.md` y `waves/A1.md`, y `panel-cuentas-y-estados-honestos/verification.md`): devueltos con `git checkout`. Los 7 mappings A9a no los tocó (comparados byte a byte con la regeneración).
- No dejó palabras inglesas en prosa española. Comentarios que siguen citando `recargar_config` en `test_respaldo.py:127` y `test_topes_por_rol.py:23`: se cambiaron a mano. Citas entre comillas invertidas repuestas a mano: `conftest.py:75`, `test_environment_isolation.py:35` y `test_attribution.py:325`/`:427`.
- Las ediciones de `apply` hechas antes en disco siguieron ahí tras los renames (comprobado: `mocked_client`, `def wrapper`, `isolate_logs`).

## Scripts (REQ-014, solo olas que renombran en src/)

| Script | `--help` | Corrida mínima o `get_file_problems` |
| --- | --- | --- |
| (ninguno) | no aplica: el lote 1 solo toca comentarios de `src/` (`config.py:229`, `attribution.py:17`) | no aplica |

## Barrido final (lote 1)

- AST (`a9a/sweep_after.py`) sobre los 5 ficheros del lote: no queda ninguna definición con un `old` del lote ni ninguna en español según el detector. Uso de código con un `old`: solo la clave `roto=` de `_agents_dir(**files)` en `test_agents.py:162`, que genera el nombre de fichero `roto.md` (dato, como `delegador=`, decisión 6).
- `git grep -w` de cada `old` en los ficheros del lote, clasificado por token: 0 en código; 139 en textos (87 docstrings, 38 cadenas y 14 comentarios). Son prosa en español y datos de prueba (`"sesion-sintetica"`, `"relleno": "x"`, `"valida"`, los ids de parametrize…). Las citas entre comillas invertidas se repusieron.
- `git grep` en todo el repo (fuera de `.sdd/` y `benchmarks/`) de los nombres propios del lote (`test_aislamiento_entorno`, `test_atribucion`, `recargar_config`, las dos fixtures autouse, `fixtures/residencia`, `fixtures/topologia`, los `test_*` del lote): 0. Los nombres comunes (`_escribir`, `_lineas`, `_espia`, `Ruta`…) que salen en otros ficheros son definiciones homónimas de otros módulos (A9a lotes 2-7, A9b, A9c y A10) o prosa.
- `residencia`/`topologia` en tests: solo quedan prosa, la línea 1 del fixture (el nombre del `.bak` real, dato) y el subcomando `llamaswap residencia` de `test_residency.py:1159`.

## Desviaciones y nombres «(plan)» ajustados

1. **Fuera de los ficheros del lote, por consecuencia mecánica** (aprobado):
   - la fixture `recargar_config`→`reload_config` arrastra sus parámetros en `test_cadenas.py`, `test_checks.py`, `test_cli_renamed_names.py` (lotes 2-4), `test_observabilidad_respaldo.py`, `test_respaldo.py`, `test_rol_fast_retirado.py`, `test_slowness.py` y `test_topes_por_rol.py`. Por eso las filas `recargar_config` de los lotes 2-4 quedan sin efecto (`apply` no encontrará nada que cambiar);
   - `backend_mock._rutas` en `test_cadenas.py:279`; el kwarg `crudo=`→`raw=` de `write_claude_desktop` en `test_checks.py:1365` (el parámetro local `crudo` de `_con_desktop` es del lote 3);
   - rutas de fixtures en `test_cadenas.py`, `test_checks.py`, `test_doctor.py`, `test_panel_estados.py`, `test_residency.py`, `test_residency_cli.py`, `test_topology.py`, `test_turn_daemon.py` y `.gitattributes:27` (conserva `-text`);
   - citas del fichero de test en `src/local_delegate/config.py:229`, `src/local_delegate/attribution.py:17`, `tests/test_cadenas.py:214` y `tests/test_commit_language.py:72`.
2. **12 filas `pycharm` → `search_edit`** (parámetros y atributos homónimos: `crudo`, `metodo`, `_pila`, `modelo`, `sesion`, `lineas`, `caso`, `_flujo`, `_espia`, `leidos`, `llamadas`, `mes`). Lección de A5b-1: con homónimos PyCharm puede elegir otro símbolo. Se editaron por línea, acotadas a su función o clase, a sus llamadas por keyword y a la cadena de `parametrize("case")`. El CSV aprobado lo anota en una línea `# Fase 2`.
3. **La anidada `delega`→`delegates` es además el nombre de una tool MCP de prueba** (`@server.tool()` toma el nombre de la función). La primera corrida dio 2 fallos en `test_attribution.py` (`call_tool("delega")` → tool desconocida). Se cambió también la cadena `"delega"` de `call_tool` (`:516`): es un nombre interno del test, no del producto.
4. **Lecciones para los lotes 2-7:** `apply` no reescribe el `def` de las anidadas (lo hace `a9a/nested_defs.py`), ni los kwargs ni las cadenas de `parametrize`. Una anidada decorada como tool MCP lleva su nombre en una cadena.

## Pendientes

A9a está cerrada (ver «Cierre de A9a», al final). Lo que A9a cede a otras olas, por destino:

**A9b (`e*`–`p*`)**
1. **`test_preguntas.py` y el test de los esquemas de `elicitation`** (hallazgo de A8a-2): el renombrado del fichero va en A9b, y el test nuevo que fija `model_json_schema()` de `ChooseModel`, `ChooseFormat` y `StartBackend` va en su lote, con su propio mutante.
2. **Carrera en `test_panel_estados.py::test_turn_wait_shown_in_panel_as_local_wait`** (la vio la sesión principal): falló una vez en el CI de Ubuntu con `'procesando' == 'en cola local'`. El bucle de espera da por buena la entrada de `inflight` en cuanto trae `turn_in_use`, sin esperar a `local_wait`. Que espere también a `local_wait`, con un control positivo que lo distinga.
3. **Lo que A8b dejó en `test_panel_estados.py`**: `_SONDEO`, `clase, texto` (:183) y la clave `modelo` de los casos (`c.modelo`). Las citas de `_extraer`/`_correr` de su docstring ya se cambiaron en el lote 7, porque esos nombres eran de `test_dashboard_js.py`.
4. **`tests/fixtures/backend/*.json`** (`error-carga.json`, `peticion-durante-carga.json`, `oom-con-perfil.json`…): son nombres en español y los usa `test_fallos_capturas.py` (`FIXTURES = … / "backend"`).
5. Homónimos de nombres de A9a que A9b renombrará por su cuenta: `_con_huerfanos` (`test_install.py`), `_escribir` (`test_enfriamiento.py`, `test_hooks_telemetry_api.py`, `test_medir_adopcion.py`, `test_test_windows.py`), `_espia` (`test_install_clients.py`, `test_preguntas.py`) y `_responde` (`test_preguntas.py`). También `_enfriar` y `CODIGO`/`LARGO`/`MECANICO` de `test_respaldo.py`, que importa `test_observabilidad_respaldo.py`.

**A9c (`q*`–`z*`)**
6. **`peticion` y `principal(…, sesion=…)` de `test_transcripts.py`**: `test_quota.py` los importa (:12) y los llama (:106, :151, :166, :204-209). Cuando A9c los renombre, cambiarán también esas llamadas de `test_quota.py`, como consecuencia mecánica.

**A10 (scripts)**
7. **Los kwargs de `ci_gate.esperar_veredicto`** (`leer=`, `reloj=`, `dormir=` y `escribir=`, en `test_ci_gate.py:175-178`), el atributo `v.estado`/`v.motivo` y las constantes `JOBS_ESPERADOS`, `INTERVALO_S`, `MAL`, `BIEN`…: son de `scripts/ci_gate.py`. Cuando A10 los renombre, `test_ci_gate.py` cambia por consecuencia (ya usa `read`, `clock` y `clock.sleep` como valores).
8. **El JS propio de `scripts/dev/capture_dashboard.py`** (`porPath`, `densidadDe`, `celda`, `clase`, `DENSIDAD`, `CLASE_TOOL`…), heredado de A8b. Del script, A9a solo cambió las rutas de test.
9. Las claves persistidas del benchmark `descartada`/`descartada_motivo`, que `test_affinity_batch.py:229-231` pasa como kwargs a `_row(**…)`, van con la decisión de A10 sobre `benchmark.py` (lectura dual o excepción).

**Sin ola (decide la sesión principal)**
10. **La clave `desconocido`** (cliente por defecto que emite `web/metrics.py:365`, lo traduce `LABELS.client` y lo afirman `test_metrics.py` y `test_dashboard_ui.py`). Si se traduce, van servidor, JS y tests a la vez.

**Intermitentes vistos en A9a** (no son de A9a; se anotan para quien los toque)
11. `test_dashboard_ui.py::test_the_kpi_unit_is_not_cut_off[ancha]` (lote 1) y `test_residency_cli.py::test_restoring_a_copy_end_to_end` (lote 7, en la corrida que tenía 12 errores de colección). Los dos pasaron sueltos y en la corrida siguiente.

---

## A9a-2 — `test_benchmark`, `test_boilerplate_salida`, `test_bump_version`, `test_cadenas` y `test_captura` (aplicado)

- Rama: `sdd/english-names-a9a-2`, apilada sobre el lote 1 (`799562a`)
- REQ cubiertos: REQ-015 (nombres de `test_benchmark.py`, `test_bump_version.py`, `test_boilerplate_salida.py`→`test_boilerplate_output.py`, `test_cadenas.py`→`test_chains.py` y `test_captura.py`→`test_capture.py`) y REQ-017
- Ficheros poseídos: esos 5 ficheros de test. Lo de fuera, en «A9a-2 · Fuera del lote»
- EOL: `evidence/A9a-2/eol-check.txt`: 0 diferencias, todo LF. Ediciones con Python y `newline=""`
- Mapping: `waves/A9a-2-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 236 filas. Filas `pycharm` 21 = filas `rename_refactoring` 21. Filas `search_edit` 215, cada una con su motivo: 209 con `make_mapping.py apply` (412 reemplazos; más el `def` de 2 anidadas, `desborde`→`overflow` y `otro`→`other`, con `a9a/nested_defs.py`), 3 pasadas de `pycharm` a `search_edit` en la fase 2 (`a9a/lineedit.py`) y 3 módulos con `git mv`
- Tests recogidos: antes 2567 → después 2567 (`evidence/A9a-2/collect.txt`), +0 −0. Por fichero, iguales: `test_benchmark.py` 36, `test_boilerplate_salida.py` 19 → `test_boilerplate_output.py` 19, `test_bump_version.py` 8, `test_cadenas.py` 27 → `test_chains.py` 27 y `test_captura.py` 4 → `test_capture.py` 4
- Suite: `evidence/A9a-2/pytest-full.log` (`pytest -q -n auto --dist loadgroup`, con `pesado.sh`), verde a la primera: 2565 pasan, 2 saltados y el aviso conocido de `BlockingPortal`, en 60 s. Esta vez no salió el fallo intermitente de `test_dashboard_ui`
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-2/ruff-check.txt`, 187 ficheros). Antes, `ruff format` reajustó `test_benchmark.py` y `test_capture.py`, a los que el rename cambió el largo de línea; esos 2 se volvieron a pasar después (40 pasan)
- Tamaño: 10 ficheros, +466 −468 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`)

### A9a-2 · Qué se hizo

1. `make_mapping.py apply`: 412 reemplazos (`test_benchmark` 226, `test_boilerplate_salida` 107, `test_cadenas` 41, `test_captura` 30, `test_bump_version` 8). Las filas `recargar_config` del lote ya no cambiaron nada (las hizo el lote 1).
2. `a9a/nested_defs.py`: el `def` de las anidadas `desborde` y `otro` de `test_benchmark.py` (los handlers del backend falso).
3. `a9a/lineedit.py`: los parámetros `texto` de `literal` (`test_benchmark.py:191`) y de `_config_llamaswap` (`test_cadenas.py:38`), y el atributo de clase `motivos` de `_SondaQueAnula` con las dos cadenas de `monkeypatch.setattr(…, "motivos", …)` (:560, :570), que PyCharm no ve.
4. PyCharm: 21 `rename_refactoring` (tabla de arriba). Esta vez no tocó nada de `.sdd/`, y los mappings 3-7 siguen iguales byte a byte.
5. `git mv` de los 3 módulos y sus citas por ruta.

### A9a-2 · Fuera del lote (consecuencia mecánica, aprobada)

- `tests/test_respaldo.py:292`: `test_cadenas.py::…` → `test_chains.py::…`.
- `test_captura.py`→`test_capture.py`: `.gitattributes:12`, `docs/wiki/Publishing.md:91`, `docs/assets/dashboard.json:11` y `scripts/dev/capture_dashboard.py:15/:23/:73`. De ese script solo cambian las rutas de test. El manifiesto conserva su `sha256` y su versión, y `test_capture.py` pasa.

### A9a-2 · Barrido final

- AST (`a9a/sweep_after.py`): ninguna definición con un `old` del lote, ninguna en español y ningún uso en código.
- `git grep -w` en los ficheros del lote, por token: 0 en código; 87 en textos (32 docstrings, 31 comentarios, 24 cadenas), prosa y datos. Repuse la cita `` `_correr` `` de `test_benchmark.py:364`. Se queda `` `otro` `` en el comentario de `test_boilerplate_output.py:297`: es el nombre de una clase de contenido del SDD `coste-api-y-cuota`, no un nombre del test.
- En el resto del repo (fuera de `.sdd/`, `benchmarks/` y `CHANGELOG.md`): 0 citas de `test_cadenas`, `test_captura` y `test_boilerplate_salida`. Los homónimos que salen (`CAPACIDAD` en `test_respaldo.py`, `MANIFIESTO` en `scripts/dev/capture_icons.py`, `_responde` en `test_preguntas.py`…) son de otros módulos (A9b, A9c y A10) o prosa.

### A9a-2 · Desviaciones

1. **3 filas `pycharm` → `search_edit`**: `texto` ×2 (parámetros homónimos) y `motivos` (atributo que se nombra también en cadenas de `monkeypatch`). Lo anota una línea `# Fase 2` del CSV.
2. Ningún test nuevo en este lote: los dos pendientes van en el lote 3 (`no_credential`) y en A9b (`elicitation`).

---

## A9a-3 — `test_causa_conexion`, `test_checks` y `test_chunking` (aplicado)

- Rama: `sdd/english-names-a9a-3`, apilada sobre el lote 2 (`584845c`)
- REQ cubiertos: REQ-015 (nombres de `test_causa_conexion.py`→`test_connection_cause.py`, `test_checks.py` y `test_chunking.py`) y REQ-017. Además, los 2 tests nuevos de `no_credential` que pedía el hallazgo de A8a-1
- Ficheros poseídos: esos 3 ficheros de test. Fuera: `tests/test_wiki.py:222` (cita un test de `test_checks.py`)
- EOL: `evidence/A9a-3/eol-check.txt`: 0 diferencias, todo LF
- Mapping: `waves/A9a-3-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 264 filas. Filas `pycharm` 21 = filas `rename_refactoring` 21. Filas `search_edit` 243, cada una con su motivo: 230 con `make_mapping.py apply` (401 reemplazos: `test_causa_conexion` 121, `test_checks` 235, `test_chunking` 45; más el `def` de 10 anidadas con `a9a/nested_defs.py`), 12 pasadas de `pycharm` a `search_edit` en la fase 2 y 1 módulo con `git mv`
- Tests recogidos: antes 2567 → después **2569 = 2567 + N, con N = 2** tests nuevos (`evidence/A9a-3/collect.txt`). Por fichero: `test_causa_conexion.py` 55 → `test_connection_cause.py` 55, `test_checks.py` 138 → 140 (+2) y `test_chunking.py` 41 → 41
- Suite: `evidence/A9a-3/pytest-full.log` (`pytest -q -n auto --dist loadgroup`, con `pesado.sh`), verde a la primera: 2567 pasan, 2 saltados y el aviso conocido de `BlockingPortal`, en 56 s
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-3/ruff-check.txt`, 187 ficheros). Antes, `ruff format` reajustó `test_checks.py` y `test_connection_cause.py`; esos 2 se volvieron a pasar después (194 pasan y 1 saltado)
- Tamaño: 4 ficheros, +478 −451 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`)

### A9a-3 · Qué se hizo

1. `make_mapping.py apply`: 401 reemplazos. `nested_defs.py`: el `def` de 10 anidadas (`_anota` ×2, `_colaborador`, `_revienta`, `pista`→`hint_for`, `explota`, `denegado`, `_registra`, `_acepta` y `seccion`).
2. **Cadenas de `parametrize`** que `apply` no toca: `("fabrica", "loopback", "esperada")`, `"codigo"` y `"viejo,nuevo"` en `test_causa_conexion.py`; `("instalada", "ultima")` y `("horas", "aviso")` en `test_checks.py`.
3. **`except … as envoltura`** (`test_causa_conexion.py:41`): `apply` no lo ve porque no es un `ast.Name`. La primera pasada dejó `except … as envoltura` con `return wrapper`; lo cazó el barrido AST antes de correr nada y se corrigió a mano.
4. `a9a/lineedit.py`: los parámetros homónimos con sus llamadas por keyword (`_fallo_real(conexion=)`, `_desktop_ctx(exige=, acepta=, llamadas=)`, `_con_desktop(crudo=)`, `_diff(archivos=, lineas=)`), y `nombre`/`esp` de la comprensión de `parametrize` (:169).
5. PyCharm: 21 `rename_refactoring`. Volvió a reescribir 5 documentos de `.sdd/`, entre ellos este registro (`A9a.md`) y `A3.md`: devueltos con `git checkout` antes de editarlo. Los mappings 3-7 no los tocó.
6. `git mv tests/test_causa_conexion.py tests/test_connection_cause.py`. Ningún fichero lo cita por ruta. Se cambió la cita de un test en su docstring (:5) y en `test_wiki.py:222`.

### A9a-3 · Tests nuevos de `no_credential`

Los pidió el hallazgo de A8a-1: el valor interno `"no_credential"` no lo protegía ningún test, porque con `"sin_credencial"` la entrada sin cabecera cae en la rama de «variable que no está», que también da `WARN` con «Claude Code», «401» y la misma pista.

- `test_an_http_entry_without_header_is_reported_as_blind_not_as_a_missing_variable`: afirma «sin cabecera de autorización» en `result.detail` y que no aparece «no está en el entorno». Falla con el mutante del hallazgo (M2a, un solo sitio a `"sin_credencial"`).
- `test_an_http_entry_without_credential_is_tagged_no_credential`: fija que `_entry_auth` devuelve `"no_credential"` para una entrada HTTP sin credencial (`None` o `""`) en los tres clientes, y `"stdio"` en stdio. Falla aunque los cuatro sitios cambien juntos y el probe quede coherente (M2b).

### A9a-3 · Barrido final

- AST (`a9a/sweep_after.py`): ninguna definición con un `old` del lote y ningún uso en código. El detector marca como español 2 nombres nuevos en inglés (`…_warns_as_suspicion`), por el sufijo «-sion»: falso positivo del detector.
- `git grep -w` en los ficheros del lote, por token: 0 en código; 168 en textos (69 docstrings, 43 comentarios y 56 cadenas). Se cambiaron las citas `` `_NUMERO_SIN_SUSTANTIVO` `` (`test_checks.py:1186`) y la del test del docstring del módulo. Se quedan `` `causa` ``, `` `detalle` `` y `` `visto` ``: son claves y valores JSON del daemon 0.34 (datos).
- Resto del repo: solo homónimos de otros módulos (`_con_huerfanos` en `test_install.py`, que es de A9b) y prosa.

### A9a-3 · Desviaciones

1. **12 filas `pycharm` → `search_edit`** (lo anota una línea `# Fase 2` del CSV): los parámetros homónimos y las variables de la comprensión.
2. **Lección para los lotes 4-7:** además del `def` de las anidadas, los kwargs y las cadenas de `parametrize`, `apply` tampoco cambia los nombres de `except … as`.

---

## A9a-4 — `test_ci_gate`, `test_cli_renamed_names`, `test_clients`, `test_conformidad_f1`, `test_core` y `test_correlacion` (aplicado)

- Rama: `sdd/english-names-a9a-4`, apilada sobre el lote 3 (`a6069f8`)
- REQ cubiertos: REQ-015 y REQ-017. Entran los nombres de `test_ci_gate.py`, `test_clients.py` (CRLF), `test_core.py`, `test_conformidad_f1.py`→`test_f1_conformance.py` y `test_correlacion.py`→`test_correlation.py`. `test_cli_renamed_names.py` solo tenía las 2 filas `recargar_config`, que ya hizo el lote 1
- Ficheros poseídos: esos 6 ficheros de test. Fuera: `src/local_delegate/resources/hooks/hook_common.py:347` (comentario que cita `tests/test_conformidad_f1.py`) y `docs/wiki/Repo-hardening.md:268` (cita un test de `test_core.py`)
- EOL: `evidence/A9a-4/eol-check.txt`: 0 diferencias. `test_clients.py` sigue CRLF y el resto LF
- Mapping: `waves/A9a-4-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 288 filas. Filas `pycharm` 18 = filas `rename_refactoring` 18. Filas `search_edit` 270, cada una con su motivo:
  - 249 con `make_mapping.py apply` (498 reemplazos: `test_ci_gate` 101, `test_clients` 148, `test_conformidad_f1` 113, `test_core` 68 y `test_correlacion` 68), más el `def` de 13 anidadas con `a9a/nested_defs.py`;
  - 19 pasadas de `pycharm` a `search_edit` en la fase 2;
  - 2 módulos con `git mv`
- Tests recogidos: 2569 → 2569 (`evidence/A9a-4/collect.txt`), +0 −0. Por fichero, iguales: 23, 21, 25, 15 (`test_f1_conformance.py`), 61 y 14 (`test_correlation.py`)
- Suite: `evidence/A9a-4/pytest-full.log` (`pytest -q -n auto --dist loadgroup`, con `pesado.sh`), verde a la primera: 2567 pasan, 2 saltados y el aviso conocido de `BlockingPortal`, en 56 s
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-4/ruff-check.txt`, 187 ficheros). Antes, `ruff format` reajustó `test_ci_gate.py`, `test_core.py` y `test_f1_conformance.py`; esos 3 se volvieron a pasar después (99 pasan)
- Tamaño: 7 ficheros, +503 −505 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`)

### A9a-4 · Qué se hizo

1. `make_mapping.py apply`: 498 reemplazos. `nested_defs.py`: el `def` de 13 anidadas (`leer` ×2 de `test_ci_gate`; `eco` ×2, `revienta` ×2, `_Sesion`, `espia`, `conversar`, `_rotar_roto`, `quien_soy` y `quien_llama` de `test_clients`; `invocar` de `test_conformidad_f1`).
2. **Tools MCP de prueba en `test_clients.py`** (lección del lote 1). Las anidadas `eco`, `quien_soy` y `quien_llama` llevan `@servidor.tool()`, así que su nombre es el de la tool. Por eso cambiaron también las cadenas:
   - `call_tool("eco", {"texto": "hola"})` (×2), con la clave del argumento `texto`→`text`;
   - `call_tool("quien_soy")` y `call_tool("quien_llama")`.
3. **`test_ci_gate.py` por búsqueda y edición** (instrucción de la sesión principal): `_correr(leer, reloj=None)` → `_run(read, clock=None)` y `_Reloj.dormir` → `_Clock.sleep`. Los kwargs de `ci_gate.esperar_veredicto` se quedan: `leer=read`, `reloj=clock`, `dormir=clock.sleep` y `escribir=output.append`. Tampoco se tocan `v.estado`/`v.motivo` ni las constantes de `ci_gate` (A10).
4. **Fixtures:**
   - `entorno`→`hook_env` (`test_conformidad_f1.py`): primero los 11 parámetros por línea y después el `rename_refactoring` de la fixture (0 usos);
   - `notas`→`notes` (`test_correlacion.py`): sus parámetros los hizo `apply` (son `function_local`) y PyCharm renombró solo el `def`;
   - `registro_limpio`→`clean_registry` es `autouse`: 0 usos.
5. Cadena de `parametrize("contenido")` → `"content"` (`test_correlacion.py:97`). En este lote no hay `except … as` con nombre en español.
6. PyCharm: 18 `rename_refactoring`. Esta vez no reescribió nada de `.sdd/`, y los mappings 5-7 siguen iguales byte a byte.

### A9a-4 · Barrido final

- AST (`a9a/sweep_after.py`): ninguna definición con un `old` del lote y ninguna en español. Usos de código con un `old`: solo los kwargs `leer=`, `reloj=` y `dormir=` (`test_ci_gate.py:177-179`) y el atributo `v.motivo` (:77, :121), que son de `scripts/ci_gate.py` (A10).
- `git grep -w` en los ficheros del lote, por token: 139 en textos (58 docstrings, 58 cadenas y 23 comentarios), todo prosa y datos. Entre los datos, el formato viejo de `enfriamiento.json` con `fallos`/`espera_s`/`hasta`, que el hook sigue leyendo. No hay citas entre comillas invertidas que cambiar.
- Resto del repo: 0 citas de `test_conformidad_f1` y `test_correlacion` tras cambiar `hook_common.py:347`. Los homónimos que salen son de A9b, A10 y del lote 6:
  - `_enfriar` y `CODIGO`/`LARGO`/`MECANICO` de `test_respaldo.py`, importados por `test_observabilidad_respaldo.py`;
  - `_correr` de `scripts/check_install_e2e.py`;
  - `_eventos` de `test_dashboard_ui.py`.

### A9a-4 · Desviaciones

1. **19 filas `pycharm` → `search_edit`** (lo anota una línea `# Fase 2` del CSV):
   - `dormir`, `leer` y `reloj` de `test_ci_gate`, por instrucción de la sesión principal;
   - `llamadas`, `texto` ×2 y `_datos` de `test_clients`;
   - `modelo` y los 11 parámetros `entorno` de `test_conformidad_f1`.
2. Las filas de las tools de prueba (`eco`, `quien_soy` y `quien_llama`) y la del parámetro `contenido` anotan en su motivo las cadenas que cambiaron con ellas.

---

## A9a-5 — `test_coste_doctor`, `test_ctrl_c`, `test_cuota`, `test_daemon`, `test_delegacion_conexion` y `test_densidad` (aplicado)

- Rama: `sdd/english-names-a9a-5`, apilada sobre el lote 4 (`d525e3f`)
- REQ cubiertos: REQ-015 y REQ-017. Entran los nombres de `test_ctrl_c.py` (CRLF), `test_daemon.py`, `test_coste_doctor.py`→`test_cost_doctor.py`, `test_cuota.py`→`test_quota.py`, `test_delegacion_conexion.py`→`test_delegation_connection.py` y `test_densidad.py`→`test_density.py`
- Ficheros poseídos: esos 6 ficheros de test. Fuera: `tests/test_transcripts.py:5`, que cita `test_cuota.py`
- EOL: `evidence/A9a-5/eol-check.txt`: 0 diferencias. `test_ctrl_c.py` sigue CRLF y el resto LF
- Mapping: `waves/A9a-5-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 299 filas. Filas `pycharm` 32 = filas `rename_refactoring` 32. Filas `search_edit` 267, cada una con su motivo:
  - 251 con `make_mapping.py apply` (569 reemplazos: `test_coste_doctor` 63, `test_ctrl_c` 51, `test_cuota` 130, `test_daemon` 57, `test_delegacion_conexion` 140 y `test_densidad` 128), más el `def`/`class` de 14 anidadas con `a9a/nested_defs.py`;
  - 12 parámetros homónimos pasados de `pycharm` a `search_edit` en la fase 2;
  - 4 módulos con `git mv`
- Tests recogidos: 2569 → 2569 (`evidence/A9a-5/collect.txt`), +0 −0. Por fichero, iguales: 6, 7, 10, 29, 14 y 16
- Suite: `evidence/A9a-5/pytest-full.log` (`pytest -q -n auto --dist loadgroup`, con `pesado.sh`), verde a la primera: 2567 pasan, 2 saltados y el aviso conocido de `BlockingPortal`, en 57 s
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-5/ruff-check.txt`, 187 ficheros). Antes, `ruff format` reajustó `test_delegation_connection.py`, `test_density.py` y `test_quota.py`; esos 3 se volvieron a pasar después (40 pasan)
- Tamaño: 7 ficheros, +565 −565 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`)

### A9a-5 · Qué se hizo

1. `make_mapping.py apply`: 569 reemplazos. `nested_defs.py`: el `def`/`class` de 14 anidadas, entre ellas `_ServidorQueRecibeCtrlC`, `_Servidor` y `_en_otro_hilo` de `test_ctrl_c`, los `_ClienteFalso` ×2 y `_solo_contesta_en_9393` de `test_daemon`, y `_preguntar`, `bloque` y `_espia` ×2 de `test_delegacion_conexion`. Ninguna es una tool MCP de prueba.
2. Cadenas de `parametrize` en `test_delegacion_conexion.py`: `"autoarranque"`→`"autostart"` y `"camino"`→`"path"`. Los `ids=` (`sin-autoarranque`, `troceada-map-reduce`…) se quedan: son el nombre visible del caso, y el número de tests no cambia.
3. `a9a/lineedit.py`: los 12 parámetros homónimos con sus llamadas por keyword (`_cotejo(sin_precio=, fuera=)`, `fila(siete=)`, `_doblar_get(registro=)`, `_doblar_get_crudo(registro=)` y `_backend(texto=)`).
4. PyCharm: 32 `rename_refactoring`. Volvió a reescribir 5 documentos de `.sdd/` (`A8b.md` y research/verification de otros SDD): devueltos a HEAD con `git checkout`. Los mappings 6-7 siguen iguales byte a byte.
5. `git mv` de los 4 módulos. Cita por ruta: `test_transcripts.py:5`. La cita `` `cotejo: null` `` de `test_cost_doctor.py:144` pasa a `` `check: null` ``, el nombre actual de esa clave del fichero de agregados (`legacy_names` lee `cotejo` como `check`).
6. En este lote no hay `except … as` con nombre en español.

### A9a-5 · Patrones de CodeQL en los ficheros renombrados (lección del lote 3)

`evidence/A9a-5/codeql-like.txt`. Un fichero de test renombrado hace que CodeQL vea sus avisos como alertas nuevas. Antes de entregar se buscaron, en `test_cost_doctor.py`, `test_quota.py`, `test_delegation_connection.py` y `test_density.py`, los patrones de `py/catch-base-exception`, `py/mixed-returns`, `py/empty-except`, `py/unused-local-variable`, `py/uninitialized-local-variable` y `py/side-effect-in-assert`.

- Herramienta: un barrido AST (`a9a/codeql_like.py`), más `ruff --select F841,BLE001,S110,E722,RET503…` y una revisión a mano de los `try/except`.
- Resultado: **0 hallazgos**, así que no hubo nada que corregir. Los dos `except Exception as e` de `test_quota.py` (:144, :158) guardan la excepción y la afirman después: no son `BaseException`, no están vacíos y sus variables se asignan en las dos ramas.
- Control positivo: el mismo barrido sobre `test_connection_cause.py` tal como estaba en `a6069f8`, antes del arreglo `2809dd1`, da las dos alertas que vio CodeQL: `except BaseException` sin relanzar en :41 y `pytest.fail` sin `raise` en `_real_failure`, :230.

### A9a-5 · Barrido final

- AST (`a9a/sweep_after.py`): ninguna definición con un `old` del lote y ninguna en español. Los únicos usos de código con un `old` son `peticion(…)` y el kwarg `sesion=` de `principal(…)` en `test_quota.py`, importados de `test_transcripts.py` (A9c).
- `git grep -w` en los ficheros del lote, por token: 141 en textos (62 docstrings, 48 comentarios y 31 cadenas), todo prosa y datos. Se queda `const casos` en el JS que `_acct_in_js` escribe a un `.mjs`: es una variable local de ese programa JS, sin relación con el parámetro Python.
- Resto del repo: 0 citas de los 4 módulos viejos. Los homónimos que salen son de otros lotes y olas.

### A9a-5 · Desviaciones

1. **12 filas `pycharm` → `search_edit`**: `fuera`, `sin_precio`, `coste`, `sesion`, `siete`, `fuente` ×2, `registro` ×2, `respuesta`, `casos` y `texto`. Lo anota una línea `# Fase 2` del CSV.
2. Las filas de `autoarranque` y `camino` anotan en su motivo la cadena de `parametrize` que cambió con ellas.

---

## A9a-6 — parte Python de `test_dashboard_ui` y `test_doctor` (aplicado)

- Rama: `sdd/english-names-a9a-6`, apilada sobre el lote 5 (`fcc6dba`)
- REQ cubiertos: REQ-015 (nombres Python de `test_dashboard_ui.py`, que es CRLF, y de `test_doctor.py`) y REQ-017. El JS de `test_dashboard_ui.py` metido en cadenas va en el lote 7
- Ficheros poseídos: esos 2 ficheros de test. Fuera: ninguno
- EOL: `evidence/A9a-6/eol-check.txt`: 0 diferencias. `test_dashboard_ui.py` sigue CRLF sin ningún LF suelto, comprobado también después de `ruff format`
- Mapping: `waves/A9a-6-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 256 filas. Filas `pycharm` 34 = filas `rename_refactoring` 34. Filas `search_edit` 222, cada una con su motivo:
  - 218 con `make_mapping.py apply` (698 reemplazos: `test_dashboard_ui` 678 y `test_doctor` 20), más el `def`/`class` de 3 anidadas (`_inyectar`, `_cifras_grandes` y `_Registrador`);
  - 4 pasadas de `pycharm` a `search_edit` en la fase 2
- Tests recogidos: 2569 → 2569 (`evidence/A9a-6/collect.txt`), +0 −0. Por fichero, iguales: `test_dashboard_ui.py` 39 y `test_doctor.py` 26. Los ids de `parametrize` son los mismos
- Suite: `evidence/A9a-6/pytest-full.log` (`pytest -q -n auto --dist loadgroup`, con `pesado.sh`), verde a la primera: 2567 pasan, 2 saltados y el aviso conocido de `BlockingPortal`, en 59 s
- Playwright entero, con el cerrojo: `evidence/A9a-6/playwright.log` (`test_dashboard_ui.py`, `test_panel_estados.py` y `test_panel_coste.py`). Pasan 78 y se salta 1 (`test_dashboard_ui.py`, el que solo aplica al CI). Se corrió antes y después de `ruff format`, con el mismo resultado
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-6/ruff-check.txt`, 187 ficheros). Antes, `ruff format` reajustó `test_dashboard_ui.py`
- Tamaño: 2 ficheros, +550 −554 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol`)

### A9a-6 · Qué se hizo

1. `make_mapping.py apply`: 698 reemplazos. `nested_defs.py`: 3 anidadas.
2. **Cadenas de `parametrize`**: `"estado"` → `"state"` (:553) y `"fuentes"` → `"fonts"` (:840, :1073 y :1166).
3. `a9a/lineedit.py`:
   - el parámetro `estado` con sus 3 usos;
   - los parámetros `cuerpo` de los dos `_json` (:368 y :922);
   - el atributo `self._hilo` (:104, :108 y :117);
   - las lambdas `lambda ruta: ruta.fulfill(…)` → `lambda route: route.fulfill(…)`. Los parámetros de las lambdas no son filas del mapping: `make_mapping` no los define. Se eligió `route` y no `path` porque son objetos `Route` de Playwright.
4. **CodeQL, `test_dashboard_ui.py:417`** (alerta abierta en `main`, `py/side-effect-in-assert`):
   - El lote tocaba esa línea al renombrar `familias`→`families`. Si se dejaba `assert "Inter" in families.pop()`, el texto de la línea cambiaba y CodeQL podía verla como alerta nueva.
   - Pasa a `assert "Inter" in next(iter(families))`. Afirma lo mismo (el único elemento del conjunto, porque el assert anterior exige `len(families) == 1`) y sin efecto lateral, así que **la alerta abierta debería cerrarse** con este lote en vez de reaparecer.
   - La aproximación AST (`evidence/A9a-6/codeql-like.txt`) da 0 hallazgos en los dos ficheros del lote y la alerta en el `test_dashboard_ui.py` de `fcc6dba` (control positivo).
5. PyCharm: 34 `rename_refactoring`. Reescribió 2 documentos de `.sdd/`, este registro (`A9a.md`, todavía sin editar en este lote) y un `verification.md` de otro SDD: devueltos a HEAD con `git checkout`. El mapping 7 sigue igual byte a byte.
6. Citas entre comillas invertidas repuestas: `` `cuantos` `` (:61) y `` `_navegador` `` (:1330).

### A9a-6 · Barrido final

- AST (`a9a/sweep_after.py`): ninguna definición con un `old` del lote y ningún uso en código. El detector marca `test_the_calibrated_quota_appears_as_a_meter` por «calibrated» (falso positivo, como el «-sion» del lote 3).
- `git grep -w` en los ficheros del lote, por token: 153 en textos (74 docstrings, 36 comentarios y 43 cadenas). Quedan los textos visibles del panel que afirman los tests y **el JS en cadenas** (`const fila`, `texto:`, `pista`…), que es del lote 7.
- Resto del repo: los homónimos que salen son de otros módulos.

### A9a-6 · Desviaciones

1. **4 filas `pycharm` → `search_edit`**: `cuerpo` ×2, `estado` y el atributo `_hilo`. Lo anota una línea `# Fase 2` del CSV.
2. **El arreglo de `py/side-effect-in-assert` en :417**: cambia la forma del assert, no lo que afirma. Va anotado en la fila `familias`.
3. Las lambdas `ruta`→`route`: fuera del mapping, anotado en las filas `cuerpo`.

---

## A9a-7 — `test_dashboard_js` y el JS en cadenas de `test_dashboard_ui` (aplicado)

- Rama: `sdd/english-names-a9a-7`, apilada sobre el lote 6 (`0dcd0cb`)
- REQ cubiertos: REQ-015 y REQ-017. Entran los nombres Python de `test_dashboard_js.py` y el JS propio de los dos tests del panel, dentro de cadenas Python: el pendiente «A9» de A8b
- Ficheros poseídos: `tests/test_dashboard_js.py` y las cadenas JS de `tests/test_dashboard_ui.py` (CRLF). Fuera: `tests/test_panel_estados.py`, que importa `_correr`/`_extraer`/`_formateadores` de `test_dashboard_js.py`. Cambian su import (que `ruff --fix` reordenó: I001) y dos citas del docstring y de un comentario
- EOL: `evidence/A9a-7/eol-check.txt`: 0 diferencias. `test_dashboard_ui.py` sigue CRLF y sin ningún LF suelto
- Mapping: `waves/A9a-7-mapping.csv` aprobado (`# approved-by-main: 2026-10-13`), 151 filas. Filas `pycharm` 11 = filas `rename_refactoring` 11. Filas `search_edit` 140, cada una con su motivo:
  - 65 Python con `make_mapping.py apply` (131 reemplazos);
  - 2 parámetros (`cuerpo` y `preludio`) pasados de `pycharm` a `search_edit` en la fase 2;
  - 73 JS: 59 de `test_dashboard_ui` y 14 de `test_dashboard_js`
- Tests recogidos: 2569 → 2569 (`evidence/A9a-7/collect.txt`), +0 −0. Por fichero, iguales: `test_dashboard_js.py` 27, `test_dashboard_ui.py` 39 y `test_panel_estados.py` 26
- Suite: `evidence/A9a-7/pytest-full.log`, verde en la segunda corrida: 2567 pasan y 2 saltados.
  - La primera (`pytest-full-run1-parametrize.log`) dio 12 errores de colección por las dos cadenas `parametrize("incluir")`, que faltaba cambiar.
  - En esa misma corrida falló `test_residency_cli.py::test_restoring_a_copy_end_to_end`, que no toca el lote: suelto pasa y en la segunda corrida también
- Playwright entero, con el cerrojo: `evidence/A9a-7/playwright.log` (`test_dashboard_ui.py`, `test_panel_estados.py` y `test_panel_coste.py`). Pasan 78 y se salta 1, el que solo aplica al CI
- `ruff check` y `ruff format --check`: limpios (`evidence/A9a-7/ruff-check.txt`, 187 ficheros). Antes:
  - `ruff check --fix` reordenó el import de `test_panel_estados.py` (I001);
  - `ruff format` reajustó `test_dashboard_js.py`.
  Después se volvieron a pasar `test_dashboard_js.py` y `test_panel_estados.py` (53 pasan)
- Tamaño: 3 ficheros de test, +324 −326 (`git diff HEAD -M30% --numstat --ignore-cr-at-eol -- tests src`)

### A9a-7 · Qué se hizo

1. `make_mapping.py apply`: 131 reemplazos en `test_dashboard_js.py`. En este lote no hay anidadas ni `except … as` en español.
2. **El JS de `test_dashboard_ui.py`**: `a9a/js_apply.py` es el script de tokens de A8b, adaptado a cadenas Python.
   - Toma el tokenizador de A0 con la posición de cada nombre y reemplaza solo los tokens `name` (nombres, `.propiedad` y `clave:`) dentro de los literales JS. No toca el texto de las cadenas JS ni los literales con escapes.
   - Lee y escribe con `newline=""`, así que conserva el CRLF.
   - Resultado: 112 tokens en 59 nombres, el mismo recuento que el inventario de la fase 1. Por ejemplo, `nota` tiene 3 tokens de nombre de 4 apariciones: la cuarta es texto.
   - Después, un pase AST cambió las **91 lecturas en Python** del resultado (`m["pista"]`, `measurements["columnaNeto"]`, `{"punto": True}`…): son las constantes de cadena que coinciden exactamente con una clave renombrada, y las 91 eran lecturas de lo que devuelve `page.evaluate`.
3. **El JS de `test_dashboard_js.py`** (fechas, :105-:183): los literales son cadenas concatenadas y f-strings, así que se editó por línea, el JS y sus lecturas a la vez (`horaLocal`→`localHour`, `desde`/`hasta`→`start`/`end`, `diaDesde`→`startDay`, `mesesDeDiferencia`→`monthsApart`…). El pase cambió también un «hoy» de la prosa del docstring (:122), que se repuso.
4. **Cadenas de `parametrize`**: `("preset", "dias")` → `"days"` y las dos `"incluir"` → `"include"`. Estas dos se olvidaron en la primera pasada y las cazó la colección (12 errores): lección repetida para A9b y A9c, que hay que repasar las cadenas de `parametrize` **antes** de correr nada.
5. `a9a/lineedit.py`: los parámetros `cuerpo`/`preludio` de `_correr` con sus 8 llamadas `preludio=`.
6. PyCharm: 11 `rename_refactoring`. Arrastró el import de `test_panel_estados.py` y reescribió 2 documentos de `.sdd/` (`A8b.md` y un `verification.md`), devueltos a HEAD.

### A9a-7 · Barrido final

- AST: ninguna definición con un `old` del lote y ningún uso en código.
- JS (`a9a/js_left.py`): ningún token `name` con un `old` de las filas `js_test_string`, y ningún nombre JS declarado ni clave en español, en los dos ficheros.
- Quedan en JS los textos visibles que afirman los tests (`'Pruebas'`, `'Delegaciones'`, «sin calibrar»…) y la variable `const casos` del `.mjs` de `test_density.py`, ya explicada en el lote 5.

### A9a-7 · Desviaciones

1. **2 filas `pycharm` → `search_edit`**: `cuerpo` y `preludio`. Lo anota una línea `# Fase 2` del CSV, que también anota el método de las filas JS.
2. Fuera del lote, por consecuencia mecánica: el import y dos citas de `test_panel_estados.py`.

---

## Cierre de A9a

- **Barrido de los 7 mappings contra sus ficheros** (`evidence/A9a-7/a9a-close-sweep.txt`):
  - ninguna definición con un `old` en ninguno de los 34 ficheros de A9a (los 32 módulos de test, `conftest.py` y `backend_mock.py`);
  - ningún token JS con un `old` de las filas `js_test_string`;
  - ninguno de los 12 módulos viejos ni de los 2 directorios de fixtures sigue en disco.

  Los únicos usos de código que quedan con un `old` son ajenos a A9a y están explicados:
  - `roto=` de `_agents_dir(**files)`: nombre de fichero, decisión 6;
  - los kwargs `leer=`/`reloj=`/`dormir=` y `v.motivo` de `ci_gate` (A10);
  - `peticion(…)` y `sesion=` de `test_transcripts` (A9c).
- **Detector** (`scripts/detect_spanish_names.py --exceptions rename-exceptions.md`; completo en `evidence/A9a-7/detector-full.json` y filtrado a los ficheros de A9a en `detector-a9a.json`): **247 hallazgos en los ficheros de A9a, ninguno pendiente de A9a**.
  - 182 `string_value` y 51 `string_key`: datos y textos. Son:
    - claves persistidas que el producto lee en su forma vieja (`leido_server_side`, `bloqueo_id`, `causa`/`detalle` del daemon 0.34, `descartada`…);
    - nombres viejos que los tests de compatibilidad usan a propósito (`LD_HOOK_READ_BLOQUEAR`, `LOCAL_DELEGATE_COSTE_RESPALDO`, `recalcular-coste`);
    - nombres de fichero e ids de prueba (`toolu_vieja`, `notas.md`, `roto.md`…);
    - fixtures del detector en `test_detect_spanish_names.py`.
  - 14 `identifier`:
    - 2 kwargs `descartada`/`descartada_motivo` (`test_affinity_batch.py`, A10);
    - 3 kwargs que dan nombre de fichero (`ajeno`, `raro`, `roto`; decisión 6);
    - 4 kwargs de `ci_gate` (A10);
    - el kwarg `LOCAL_DELEGATE_COSTE_RESPALDO` de `reload_config(**env)` (nombre viejo que el test pone a propósito);
    - `sesion` (A9c);
    - 3 falsos positivos del detector en nombres ingleses (`…_as_suspicion` ×2 por «-sion», `…_calibrated_quota…`).
- **Tests recogidos**: `evidence/A9a/collect-before.txt` 2567 → `evidence/A9a-7/collect.txt` **2569 = 2567 + 2**. Los 2 son los tests nuevos de `no_credential` del lote 3; no se perdió ninguno.
- **Mappings**: 1788 filas en 7 lotes, todas aplicadas. 174 `pycharm` = 174 `rename_refactoring`. Las filas que pasaron de `pycharm` a `search_edit` en la fase 2 suman 64 (12 + 3 + 12 + 19 + 12 + 4 + 2) y cada lote las anota en una línea `# Fase 2` de su CSV.
- **Lecciones para A9b y A9c** (además de las del brief):
  1. `apply` no cambia el `def` de las anidadas, los kwargs, las cadenas de `parametrize`, los nombres de `except … as` ni los parámetros de las lambdas.
  2. Una anidada con `@server.tool()` lleva su nombre, y el de sus argumentos, en las cadenas de `call_tool`.
  3. Un fichero de test renombrado hace que CodeQL vea sus avisos como alertas nuevas.
  4. PyCharm reescribe documentos de `.sdd/` en casi todos los lotes.
  5. Las fixtures `autouse` y las que piden parámetros `function_local` dan «0 usos» en PyCharm, y es lo esperado.
