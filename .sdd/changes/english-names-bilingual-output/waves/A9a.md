# Ola A9a — Tests `conftest.py`, fixtures de datos y módulos `a*`–`d*`

La subola se parte en 7 lotes (D13: 1788 filas, máximo 300 por lote y sin partir un módulo, salvo
la excepción aprobada del JS de `test_dashboard_ui.py`, que va al lote 7). Cada lote es un commit
que hace la sesión principal, en una rama apilada sobre el anterior. Los **lotes 1 y 2** están en `main`
(`2860497`, PR #272; `b10b468`, PR #273) y el **lote 3** en el commit `a6069f8` (PR #274). El
**lote 4** está aplicado y registrado en la sección «A9a-4», al final. Las tablas de controles
positivos, `local_*` y PyCharm son las de los lotes ya aplicados, porque `check_wave_records.py` lee
la primera tabla de cada sección: 37 + 21 + 21 + 18 = 97 filas `rename_refactoring` = 97 filas
`pycharm` de los mappings A9a-1 a A9a-4.

- Rama: lote 1 en `sdd/english-names-a9a`, desde `main` en `f4a869f` (A8b mezclada), commit `799562a` (PR #272); lote 2 en `sdd/english-names-a9a-2`, commit `584845c` (PR #273), rebasado sobre `main` con el lote 1 (`2860497`); lote 3 en `sdd/english-names-a9a-3`, commit `a6069f8` (PR #274), rebasado sobre `main`; lote 4 en `sdd/english-names-a9a-4`, apilada sobre `a6069f8` · Commit del lote 4: pendiente, con el borrador en `waves/A9a-4-commit-msg.txt` (firmado y sin coautoría)
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

## Llamadas `local_*` (sesión principal y cada agente)

| Quién | Tool | Para qué | Resultado (útil / corregido / descartado) |
| --- | --- | --- | --- |
| agente A9a-1 | `local_lint_summary(path=evidence/A9a-1/pytest-full.log)` | resumen de la suite | útil: solo los 12 avisos de `BlockingPortal` de Starlette, ningún fallo |
| agente A9a-2 | `local_lint_summary(path=evidence/A9a-2/pytest-full.log)` | resumen de la suite del lote 2 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-3 | `local_lint_summary(path=evidence/A9a-3/pytest-full.log)` | resumen de la suite del lote 3 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |
| agente A9a-4 | `local_lint_summary(path=evidence/A9a-4/pytest-full.log)` | resumen de la suite del lote 4 | útil: solo los 12 avisos de `BlockingPortal`, ningún fallo |

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

- **Tests nuevos sin renombrado** (respuesta de la sesión principal): el test de `no_credential` («Hallazgos» de A8a-1) está hecho en el lote 3 (2 tests nuevos en `test_checks.py`). El test que fija los esquemas de `elicitation` es de `test_preguntas.py`: va en A9b.
- **A9b:** `tests/fixtures/backend/*.json` (nombres en español, los usa `test_fallos_capturas.py`); `test_preguntas.py`; lo de `test_panel_estados.py` heredado de A8b.
- **Lotes 2-7:** aplicar sus mappings con las lecciones de arriba.

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
